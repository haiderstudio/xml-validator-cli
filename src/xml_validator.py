"""xml-validator-cli: check XML files are well-formed, fail CI on a bad file.

Reads one or more XML files (or folders of them), checks each one
parses as well-formed XML with Python's standard library parser,
and reports every bad file with the file, the line number, and the
exact parser error. Report-only: it never rewrites a file.
Exit 0 when every file is clean, 1 when any problem is found,
2 for a usage error.
"""

import argparse
import fnmatch
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

__version__ = "1.0.0"

XML_EXTENSIONS = {".xml", ".xsl", ".xsd", ".svg", ".rss"}

_POSITION_SUFFIX = re.compile(r": line \d+, column \d+$")


class Problem:
    """One problem in one file: path, line number, plain reason."""

    def __init__(self, path, line, reason):
        self.path = path
        self.line = line
        self.reason = reason

    def text(self):
        return f"{self.path}:{self.line}: {self.reason}"

    def as_dict(self):
        return {"file": self.path, "line": self.line, "reason": self.reason}


def clean_reason(message):
    """Strip the parser's trailing ': line N, column M' from a message."""
    return _POSITION_SUFFIX.sub("", message).strip()


def check_bytes(data, label):
    """Check one XML document (as bytes) and return its problems.

    An XML parser stops at the first error, so a bad file reports
    one problem: the first thing the parser trips on, with its
    line number. Fix that, run again, and the next error shows.
    """
    try:
        ET.fromstring(data)
        return []
    except ET.ParseError as exc:
        line = exc.position[0] if exc.position else 1
        return [Problem(label, line, clean_reason(str(exc)))]


def check_text(text, label):
    """Check one XML document (as text) and return its problems."""
    return check_bytes(text.encode("utf-8"), label)


def check_file(path):
    """Check one file on disk and return its problems."""
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        return [Problem(str(path), 0, f"cannot read file: {exc.strerror}")]
    if not data:
        return [Problem(str(path), 1, "file is empty")]
    return check_bytes(data, str(path))


def _is_excluded(path, patterns):
    name = path.name
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def collect(paths, recursive=True, exclude=()):
    """Gather the files to check from the given paths.

    A file given directly is always checked, whatever its name.
    A folder is walked for XML files only. `.git` folders are
    never walked, and directory links are never followed.
    Returns (files, error) where error names a missing path,
    or None when every path exists.
    """
    files = []
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            return [], f"no such file or folder: {raw}"
        if path.is_file():
            if not _is_excluded(path, exclude):
                files.append(path)
            continue
        for root, dirs, names in os.walk(path, followlinks=False):
            dirs[:] = sorted(
                d for d in dirs if d != ".git" and not _is_excluded(Path(d), exclude)
            )
            for name in sorted(names):
                candidate = Path(root) / name
                if candidate.suffix.lower() in XML_EXTENSIONS:
                    if not _is_excluded(candidate, exclude):
                        files.append(candidate)
            if not recursive:
                break
    seen = set()
    unique = []
    for path in files:
        key = str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique, None


def run(paths, recursive=True, exclude=(), stdin=False, json_out=False):
    """Check the inputs and print the report. Returns the exit code."""
    problems = []
    if stdin:
        data = sys.stdin.buffer.read()
        if not data:
            problems = [Problem("<stdin>", 1, "input is empty")]
        else:
            problems = check_bytes(data, "<stdin>")
        files_checked = 1
    else:
        files, error = collect(paths, recursive=recursive, exclude=exclude)
        if error is not None:
            print(f"xml-validator: {error}", file=sys.stderr)
            return 2
        files_checked = len(files)
        for path in files:
            problems.extend(check_file(path))
    files_with_problems = len({p.path for p in problems})
    if json_out:
        print(json.dumps({
            "files_checked": files_checked,
            "problems": [p.as_dict() for p in problems],
            "files_with_problems": files_with_problems,
        }, indent=2))
        out = sys.stderr
    else:
        out = sys.stdout
    if not problems:
        print(f"OK — {files_checked} file(s) checked, "
              f"all XML files are well-formed.", file=out)
        return 0
    if json_out:
        for problem in problems:
            print(problem.text(), file=sys.stderr)
    else:
        for problem in problems:
            print(problem.text())
    print(f"Checked {files_checked} file(s), {len(problems)} problem(s) "
          f"in {files_with_problems} file(s).", file=out)
    return 1


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="xml_validator",
        description="Check XML files are well-formed, fail CI on a bad file.")
    parser.add_argument("paths", nargs="*", metavar="PATH",
                        help="XML file or folder to check")
    parser.add_argument("--stdin", action="store_true",
                        help="check one XML document from standard input")
    parser.add_argument("--json", action="store_true",
                        help="print the result as JSON")
    parser.add_argument("--no-recursive", action="store_true",
                        help="do not walk into subfolders")
    parser.add_argument("--exclude", action="append", default=[],
                        metavar="PATTERN",
                        help="skip files and folders by name pattern "
                             "(repeatable)")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)
    if not args.stdin and not args.paths:
        parser.error("give at least one file or folder, or use --stdin")
    return run(args.paths, recursive=not args.no_recursive,
               exclude=args.exclude, stdin=args.stdin,
               json_out=args.json)


if __name__ == "__main__":
    sys.exit(main())
