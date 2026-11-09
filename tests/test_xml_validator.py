"""Tests for xml-validator-cli. Standard library only."""

import ast
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = ROOT / "src" / "xml_validator.py"

sys.path.insert(0, str(ROOT / "src"))
import xml_validator
from xml_validator import Problem, check_bytes, check_file, check_text, clean_reason, collect


def problems_as_tuples(data, **kwargs):
    if isinstance(data, str):
        return [(p.line, p.reason) for p in check_text(data, "test.xml", **kwargs)]
    return [(p.line, p.reason) for p in check_bytes(data, "test.xml", **kwargs)]


def run_cli(*args, input_data=None):
    """Run the CLI as a subprocess; return (exit code, stdout, stderr)."""
    result = subprocess.run(
        [sys.executable, str(SRC), *args],
        input=input_data, capture_output=True)
    return (result.returncode,
            result.stdout.decode("utf-8"),
            result.stderr.decode("utf-8"))


class TestCleanReason(unittest.TestCase):
    def test_strips_position_suffix(self):
        self.assertEqual(clean_reason("mismatched tag: line 4, column 2"),
                         "mismatched tag")

    def test_leaves_plain_message_alone(self):
        self.assertEqual(clean_reason("file is empty"), "file is empty")


class TestValidDocumentsPass(unittest.TestCase):
    def test_simple_document(self):
        self.assertEqual(problems_as_tuples("<root><a>ok</a></root>"), [])

    def test_declaration_comment_pi_cdata_doctype(self):
        doc = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               '<!-- a comment -->\n'
               '<?pi some data?>\n'
               '<!DOCTYPE root>\n'
               '<root><a><![CDATA[ <not a tag> ]]></a></root>')
        self.assertEqual(problems_as_tuples(doc), [])

    def test_namespaces_and_attributes(self):
        doc = ('<root xmlns="http://example.com/ns" '
               'xmlns:x="http://example.com/x">'
               '<x:item id="1" flag="true" />'
               '</root>')
        self.assertEqual(problems_as_tuples(doc), [])

    def test_valid_but_schema_would_fail(self):
        # Well-formedness only: unknown elements and no schema
        # reference are NOT a failure here.
        self.assertEqual(
            problems_as_tuples("<root><unknown>1</unknown></root>"), [])

    def test_bom_crlf_and_latin1_declared(self):
        self.assertEqual(
            problems_as_tuples(b"\xef\xbb\xbf<root><a>x</a></root>"), [])
        self.assertEqual(
            problems_as_tuples(b"<root>\r\n<a>x</a>\r\n</root>"), [])
        self.assertEqual(
            problems_as_tuples(
                b'<?xml version="1.0" encoding="ISO-8859-1"?>'
                b"<root>caf\xe9</root>"), [])


class TestBrokenDocumentsFail(unittest.TestCase):
    def test_unclosed_tag_exact_line(self):
        doc = "<root>\n  <a>text\n  <b>more</b>\n"
        self.assertEqual(problems_as_tuples(doc),
                         [(4, "no element found")])

    def test_mismatched_tag_exact_line(self):
        doc = "<root>\n  <a>text\n  <b>more</b>\n</root>"
        self.assertEqual(problems_as_tuples(doc),
                         [(4, "mismatched tag")])

    def test_mismatched_on_one_line(self):
        self.assertEqual(
            problems_as_tuples("<root><a>text</b></root>"),
            [(1, "mismatched tag")])

    def test_two_roots_exact_line(self):
        self.assertEqual(problems_as_tuples("<a/>\n<b/>"),
                         [(2, "junk after document element")])

    def test_junk_after_document(self):
        self.assertEqual(problems_as_tuples("<root/> trailing"),
                         [(1, "junk after document element")])

    def test_undefined_entity_exact_line(self):
        doc = ("<root>\n  <a>x</a>\n  <b>Tom &nope; Jerry</b>\n</root>")
        self.assertEqual(problems_as_tuples(doc),
                         [(3, "undefined entity")])

    def test_duplicate_attribute_exact_line(self):
        doc = ('<root>\n  <a x="1" x="2" />\n</root>')
        self.assertEqual(problems_as_tuples(doc),
                         [(2, "duplicate attribute")])

    def test_unquoted_attribute(self):
        self.assertEqual(problems_as_tuples('<root a=1/>'),
                         [(1, "not well-formed (invalid token)")])

    def test_empty_document(self):
        self.assertEqual(problems_as_tuples(""),
                         [(1, "no element found")])

    def test_null_byte(self):
        self.assertEqual(problems_as_tuples(b"<root>a\x00b</root>"),
                         [(1, "not well-formed (invalid token)")])

    def test_latin1_bytes_declared_utf8(self):
        data = (b'<?xml version="1.0" encoding="UTF-8"?>'
                b"<root>caf\xe9</root>")
        self.assertEqual(problems_as_tuples(data),
                         [(1, "not well-formed (invalid token)")])

    def test_parser_stops_at_first_error(self):
        # A parser reports the first error only; fix it and run
        # again for the next one. Two errors, one problem.
        doc = "<root><a>text</b><c>more</d></root>"
        problems = problems_as_tuples(doc)
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0][1], "mismatched tag")


class TestCheckFile(unittest.TestCase):
    def test_missing_file(self):
        problems = check_file(Path("/definitely/not/here.xml"))
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0].line, 0)
        self.assertIn("cannot read file", problems[0].reason)

    def test_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.xml"
            path.write_bytes(b"")
            self.assertEqual(
                [(p.line, p.reason) for p in check_file(path)],
                [(1, "file is empty")])

    def test_input_file_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.xml"
            path.write_text("<root><a>x</b></root>")
            before = path.read_bytes()
            check_file(path)
            self.assertEqual(path.read_bytes(), before)


class TestParserCrossCheck(unittest.TestCase):
    """The checker agrees with ElementTree on a corpus of snippets."""

    CORPUS = [
        "<root/>",
        "<root><a>ok</a></root>",
        "<root><a>text</root>",
        "<root><a>text</b></root>",
        "<a/><b/>",
        "<root/> trailing",
        "<root>&nope;</root>",
        "<root>&amp;ok</root>",
        "",
        "   \n  ",
        '<root a="1" a="2"/>',
        "<root a=1/>",
        "<root>\n  <a>x</a>\n</root>",
        "<root>\n  <a>x\n</root>",
        "<?xml version=\"1.0\"?><root/>",
        "<root><![CDATA[ <x> ]]></root>",
        "<root><!-- c --><a/></root>",
        "<root>caf\xc3\xa9</root>",
    ]

    def test_agrees_with_elementtree(self):
        for doc in self.CORPUS:
            with self.subTest(doc=doc):
                problems = check_text(doc, "test.xml")
                try:
                    ET.fromstring(doc)
                    parses = True
                    position = None
                except ET.ParseError as exc:
                    parses = False
                    position = exc.position
                if parses:
                    self.assertEqual(problems, [])
                else:
                    self.assertEqual(len(problems), 1)
                    self.assertEqual(problems[0].line, position[0])


class TestCollect(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        (self.base / "a.xml").write_text("<root/>")
        (self.base / "b.txt").write_text("<root/>")
        (self.base / "c.XSL").write_text("<root/>")
        (self.base / "sub").mkdir()
        (self.base / "sub" / "d.svg").write_text("<svg/>")
        (self.base / "sub" / "e.xml").write_text("<root/>")
        git = self.base / ".git"
        git.mkdir()
        (git / "hooks.xml").write_text("<root/>")

    def test_folder_walks_xml_extensions_only(self):
        files, error = collect([str(self.base)])
        self.assertIsNone(error)
        names = sorted(str(p.relative_to(self.base)) for p in files)
        self.assertEqual(names, ["a.xml", "c.XSL", "sub/d.svg", "sub/e.xml"])

    def test_git_folder_skipped(self):
        files, _ = collect([str(self.base)])
        self.assertNotIn(str(self.base / ".git" / "hooks.xml"),
                         [str(p) for p in files])

    def test_direct_file_any_name(self):
        files, error = collect([str(self.base / "b.txt")])
        self.assertIsNone(error)
        self.assertEqual([str(p) for p in files], [str(self.base / "b.txt")])

    def test_no_recursive(self):
        files, _ = collect([str(self.base)], recursive=False)
        names = sorted(str(p.relative_to(self.base)) for p in files)
        self.assertEqual(names, ["a.xml", "c.XSL"])

    def test_exclude_pattern(self):
        files, _ = collect([str(self.base)], exclude=["a.xml", "sub"])
        names = sorted(str(p.relative_to(self.base)) for p in files)
        self.assertEqual(names, ["c.XSL"])

    def test_dedupe(self):
        files, _ = collect([str(self.base / "a.xml"),
                            str(self.base / "a.xml")])
        self.assertEqual(len(files), 1)

    def test_missing_path_is_an_error(self):
        files, error = collect([str(self.base / "nope.xml")])
        self.assertEqual(files, [])
        self.assertIn("no such file or folder", error)


class TestCli(unittest.TestCase):
    def test_clean_file_exit_zero(self):
        code, out, _ = run_cli("examples/good.xml")
        self.assertEqual(code, 0)
        self.assertEqual(
            out, "OK — 1 file(s) checked, all XML files are well-formed.\n")

    def test_bad_file_exit_one_and_exact_output(self):
        code, out, _ = run_cli("examples/bad.xml")
        self.assertEqual(code, 1)
        self.assertEqual(
            out, "examples/bad.xml:7: no element found\n"
                 "Checked 1 file(s), 1 problem(s) in 1 file(s).\n")

    def test_folder_exit_one_and_exact_output(self):
        code, out, _ = run_cli("examples")
        self.assertEqual(code, 1)
        self.assertEqual(
            out, "examples/bad-entity.xml:5: undefined entity\n"
                 "examples/bad.xml:7: no element found\n"
                 "examples/mismatched.xml:4: mismatched tag\n"
                 "examples/two-roots.xml:7: junk after document element\n"
                 "examples/configs/app.xml:4: duplicate attribute\n"
                 "Checked 7 file(s), 5 problem(s) in 5 file(s).\n")

    def test_stdin_clean(self):
        code, out, _ = run_cli("--stdin",
                              input_data=b"<root><a>ok</a></root>")
        self.assertEqual(code, 0)
        self.assertIn("all XML files are well-formed", out)

    def test_stdin_broken(self):
        code, out, _ = run_cli("--stdin",
                              input_data=b"<root><a>ok</b></root>")
        self.assertEqual(code, 1)
        self.assertIn("<stdin>:1: mismatched tag", out)

    def test_stdin_empty(self):
        code, out, _ = run_cli("--stdin", input_data=b"")
        self.assertEqual(code, 1)
        self.assertIn("<stdin>:1: input is empty", out)

    def test_json_clean_stdout_parses(self):
        code, out, err = run_cli("examples/good.xml", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {
            "files_checked": 1, "problems": [], "files_with_problems": 0})
        self.assertIn("all XML files are well-formed", err)

    def test_json_broken_stdout_parses(self):
        code, out, err = run_cli("examples/configs/app.xml", "--json")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out), {
            "files_checked": 1,
            "problems": [{
                "file": "examples/configs/app.xml",
                "line": 4,
                "reason": "duplicate attribute",
            }],
            "files_with_problems": 1})
        self.assertIn("examples/configs/app.xml:4: duplicate attribute", err)

    def test_missing_path_exit_two(self):
        code, _, err = run_cli("does-not-exist.xml")
        self.assertEqual(code, 2)
        self.assertIn("no such file or folder", err)

    def test_no_args_exit_two(self):
        code, _, err = run_cli()
        self.assertEqual(code, 2)
        self.assertIn("give at least one file or folder", err)

    def test_version(self):
        code, out, _ = run_cli("--version")
        self.assertEqual(code, 0)
        self.assertEqual(out, "xml_validator 1.0.0\n")

    def test_run_example_matches_sample_output(self):
        result = subprocess.run(
            ["sh", "examples/run-example.sh"],
            cwd=ROOT, capture_output=True)
        self.assertEqual(result.returncode, 1)
        expected = (ROOT / "examples" / "sample-output.md").read_bytes()
        self.assertEqual(result.stdout, expected)

    def test_readme_quotes_match_live_output(self):
        readme = (ROOT / "README.md").read_text()
        for snippet in [
            "OK — 1 file(s) checked, all XML files are well-formed.",
            "examples/bad.xml:7: no element found",
            "examples/mismatched.xml:4: mismatched tag",
            "examples/two-roots.xml:7: junk after document element",
            "examples/bad-entity.xml:5: undefined entity",
            "examples/configs/app.xml:4: duplicate attribute",
            "Checked 7 file(s), 5 problem(s) in 5 file(s).",
        ]:
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, readme)


class TestExamples(unittest.TestCase):
    def test_good_and_sitemap_pass(self):
        for name in ["examples/good.xml", "examples/sitemap.xml"]:
            with self.subTest(name=name):
                code, _, _ = run_cli(name)
                self.assertEqual(code, 0)

    def test_each_bad_example_fails_with_one_problem(self):
        expected = {
            "examples/bad.xml": (7, "no element found"),
            "examples/mismatched.xml": (4, "mismatched tag"),
            "examples/two-roots.xml": (7, "junk after document element"),
            "examples/bad-entity.xml": (5, "undefined entity"),
            "examples/configs/app.xml": (4, "duplicate attribute"),
        }
        for name, (line, reason) in expected.items():
            with self.subTest(name=name):
                problems = check_file(ROOT / name)
                self.assertEqual(
                    [(p.line, p.reason) for p in problems],
                    [(line, reason)])


class TestStdlibOnly(unittest.TestCase):
    def test_source_imports_only_stdlib(self):
        tree = ast.parse(SRC.read_text())
        stdlib = set(sys.stdlib_module_names)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        non_stdlib = imported - stdlib
        self.assertEqual(non_stdlib, set())

    def test_no_yaml_anywhere_in_src_or_ci(self):
        for path in [SRC, ROOT / ".github" / "workflows" / "ci.yml"]:
            self.assertNotIn("yaml", path.read_text())

    def test_ci_runs_only_the_stdlib_test(self):
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        self.assertIn("python3 tests/test_xml_validator.py", ci)
        self.assertIn("actions/checkout@v4", ci)
        self.assertIn("actions/setup-python@v5", ci)


class TestHygiene(unittest.TestCase):
    BANNED = ["TODO", "FIXME", "coming soon", "lorem", "Lorem"]
    SECRET_WORDS = ["api_key", "password", "client_secret"]

    def test_no_placeholder_text(self):
        hits = []
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if ".git" in path.parts or "__pycache__" in path.parts:
                continue
            if "tests" in path.parts:
                continue
            text = path.read_bytes().decode("utf-8", errors="ignore")
            for word in self.BANNED:
                if word in text:
                    hits.append(f"{path.relative_to(ROOT)}: {word}")
        self.assertEqual(hits, [])

    def test_no_secrets_or_absolute_paths(self):
        hits = []
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if ".git" in path.parts or "__pycache__" in path.parts:
                continue
            if "tests" in path.parts:
                continue
            text = path.read_bytes().decode("utf-8", errors="ignore")
            for word in self.SECRET_WORDS + ["/home/hatch", "/Users/"]:
                if word in text:
                    hits.append(f"{path.relative_to(ROOT)}: {word}")
        self.assertEqual(hits, [])

    def test_gitignore_lists_env_first(self):
        lines = (ROOT / ".gitignore").read_text().splitlines()
        self.assertEqual(lines[0], ".env")

    def test_license_present(self):
        self.assertTrue((ROOT / "LICENSE").exists())
        self.assertIn("MIT License", (ROOT / "LICENSE").read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
