# xml-validator-cli

Check XML files are well-formed, fail CI on a bad file.

[![CI](https://github.com/haiderstudio/xml-validator-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/haiderstudio/xml-validator-cli/actions/workflows/ci.yml) [![Licence: MIT](https://img.shields.io/badge/Licence-MIT-yellow.svg)](LICENSE)

## What it does

`xml_validator` reads an XML file and checks it parses as
well-formed XML with Python's standard library parser — matching
tags, one root, valid structure — and reports every bad file
with the file, the line number, and the exact parser error.
It exits 1 when any problem is found, so it can fail a CI run.
A clean file exits 0.

- A bad XML file breaks every parser that reads it — configs,
  RSS feeds, sitemaps, SVG assets — with a cryptic error. This
  tool catches the break before the file ships, and points at
  the exact line.
- Checks: an unclosed tag, mismatched tags, two roots in one
  document, junk after the document element, an undefined
  entity (`&nope;`), a duplicate attribute, an unquoted
  attribute value, a bad byte, and an empty file.
- A file that is valid XML passes even if it would fail a
  schema — this tool checks well-formedness only, never
  validates against a schema.
- An XML parser stops at the first error in a file, so a bad
  file reports one problem: the first thing the parser trips
  on. Fix that, run again, and the next error shows.
- A file given directly on the command line is always checked,
  whatever its name. A folder is walked for `.xml`, `.xsl`,
  `.xsd`, `.svg`, and `.rss` files, recursively by default
  (`--no-recursive` stops at the top level). `.git` folders
  are never walked, and directory links are never followed.
  `--exclude` skips files and folders by name pattern.
- `--json` prints the result as JSON (the human-readable
  lines go to standard error), and `--stdin` checks one
  XML document read from standard input.

## Who it is for

Anyone who ships XML files — app developers, teams that keep
config in version control, feed and sitemap owners, and anyone
who has ever stared at a parser error that turned out to be
one bad line in an XML file.

## What it does NOT do

- It does not check whether the XML is *right* — a
  well-formed file can still hold a wrong value, and a file
  that breaks its schema still passes here. Checking content
  against a schema is a different job.
- It does not convert or rewrite anything. It is report-only,
  and it never touches the network.
- It does not check any other format. INI is repo #54's
  ini-validator-cli, TOML is repo #36's toml-validator-cli,
  JSON is repo #19's json-formatter-validator-cli — XML is a
  different format.

## How this differs

- itplr-kosit/validator (193 stars) validates XML documents
  against XML Schema and Schematron. That is a heavier job:
  schema validation, not a well-formedness check.
- NaturalIntelligence/fast-xml-parser (3,139 stars) is a
  JavaScript parsing library. A library you code against is
  not a file checker you run in CI.
- sissaschool/xmlschema (475 stars) is a Python
  schema-validation library, not a command-line tool.
- Mat001/XML_well_formedness_checker (3 stars) is a Python
  app that checks well-formedness, last touched in May 2015.
  It has no tests and no CI gate; this tool is a tested
  command-line tool with a line number for every problem,
  folder walking, `--json`, and `--stdin`.
- volkadav/xwf (0 stars) is a small C checker with no CI gate.
- There is no exact-name rival: a GitHub search for
  `"xml-validator-cli"` returns 1 result, a 0-star SCORM
  e-learning package validator — a different job
  (checked Nov 8, 2026).

## Install

Python 3.10 or newer, nothing else to install.

```sh
git clone https://github.com/haiderstudio/xml-validator-cli.git
cd xml-validator-cli
```

## Usage

Check one file:

```sh
python3 src/xml_validator.py examples/good.xml
```

```text
OK — 1 file(s) checked, all XML files are well-formed.
```

Check a broken file:

```sh
python3 src/xml_validator.py examples/bad.xml
```

```text
examples/bad.xml:7: no element found
Checked 1 file(s), 1 problem(s) in 1 file(s).
```

The exit code is 1, so a CI run fails.

Check a whole folder:

```sh
python3 src/xml_validator.py examples
```

```text
examples/bad-entity.xml:5: undefined entity
examples/bad.xml:7: no element found
examples/mismatched.xml:4: mismatched tag
examples/two-roots.xml:7: junk after document element
examples/configs/app.xml:4: duplicate attribute
Checked 7 file(s), 5 problem(s) in 5 file(s).
```

Check one document from standard input:

```sh
printf '<root><a>ok</a></root>' | python3 src/xml_validator.py --stdin
```

```text
OK — 1 file(s) checked, all XML files are well-formed.
```

Machine-readable output:

```sh
python3 src/xml_validator.py examples/configs/app.xml --json
```

```json
{
  "files_checked": 1,
  "problems": [
    {
      "file": "examples/configs/app.xml",
      "line": 4,
      "reason": "duplicate attribute"
    }
  ],
  "files_with_problems": 1
}
```

## Examples

- `examples/good.xml` — a clean app config with a comment,
  CDATA, and attributes. Passes.
- `examples/bad.xml` — the closing `</config>` tag is
  missing. Fails with exit 1.
- `examples/mismatched.xml` — `<host>` is closed by
  `</hostname>`. Fails with exit 1.
- `examples/two-roots.xml` — one document, two root
  elements. Fails with exit 1.
- `examples/bad-entity.xml` — an undefined entity
  (`&nope;`). Fails with exit 1.
- `examples/sitemap.xml` — a clean sitemap with two URLs.
  Passes, and shows a real-world file shape.
- `examples/configs/app.xml` — a duplicate attribute, in a
  subfolder. Fails with exit 1.
- `sh examples/run-example.sh` runs the checker on the whole
  `examples/` folder. Its output is in
  `examples/sample-output.md`.

## How it is tested

```sh
python3 tests/test_xml_validator.py
```

The tests cover: valid documents that must pass (declaration,
comments, processing instructions, CDATA, DOCTYPE,
namespaces, attributes, byte-order mark, CRLF line endings,
Latin-1 declared as Latin-1), every problem type with exact
line numbers (unclosed tag, mismatched tag, two roots, junk
after the document element, undefined entity, duplicate
attribute, unquoted attribute, empty file, null byte,
Latin-1 bytes declared as UTF-8), a valid document that
would fail a schema passing, the parser stopping at the
first error, folder walking (XML extensions only, `.git`
skipped, `--no-recursive`, `--exclude`, dedupe), `--stdin`,
`--json`, exit codes 0/1/2, and the bundled examples (the
sample output is compared byte-for-byte against a fresh run).

The tests also cross-check the checker against Python's own
`xml.etree.ElementTree`: on a corpus of XML snippets, the
checker reports a problem exactly when the parser refuses
to parse the file, and its reported line matches the
parser's error line.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT — see [LICENSE](LICENSE).

## Original work

This tool was written from scratch for this repo. The XML
rules it checks are the rules of Python's standard library
`xml.etree.ElementTree` parser, verified against that
parser's own behaviour. The idea of validating XML files is
a common one; the code, the wording, and the tests are
original.
