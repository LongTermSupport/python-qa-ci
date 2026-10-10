"""Resolving any printed identifier to its documentation, offline, and the dangling-docs check."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from py_qa.finding import Finding
from py_qa.tools import BUNDLED_PLUGIN

if TYPE_CHECKING:
    from py_qa.config import Config, ProjectCheck
    from py_qa.defences import Defence

BUNDLED_DOCS = Path(__file__).parent / "docs" / "rules"
DANGLING = "pyqaci.docs.dangling"
REQUIRED_SECTIONS = ("## What it flags", "## Why", "## How to fix correctly")
_PREFIX = re.compile(r"^(?:ruff|pylint|mypy|pyright|bandit|semgrep|coverage)::")


def missing_sections(page: str) -> list[str]:
    """Return the required headings a documentation page lacks."""
    headings = {line.strip() for line in page.splitlines()}
    return [section for section in REQUIRED_SECTIONS if section not in headings]


def resolve(identifier: str, config: Config) -> str | None:
    """Return the documentation for an identifier exactly as printed, or None if nothing has it.

    The order is the bundled pages, the project's own pages under docs_dir, the project's
    checks, then the catalogues Pylint, Ruff and mypy ship with their installed copies, and last
    the project's rule_doc_command.
    """
    found = _resolve_known(identifier, config)
    if found is None and config.rule_doc_command is not None:
        found = _project_rule_doc(identifier, config)
    return found


def _resolve_known(identifier: str, config: Config) -> str | None:
    name = _PREFIX.sub("", identifier)
    symbol = _pylint_symbol(name, config) or name
    for directory in (BUNDLED_DOCS, config.root / config.docs_dir):
        for candidate in (name, symbol):
            page = directory / f"{candidate}.md"
            if page.is_file():
                return page.read_text(encoding="utf-8")
    check = next((check for check in config.checks if check.name == name), None)
    if check is not None:
        return _check_doc(check, config)
    if identifier.partition("::")[0] in {*_UNROUTED_TOOLS, "coverage"}:
        # A Bandit B-code is not Ruff's flake8-bugbear code of the same number.
        return _route_doc(identifier)
    found = _pylint_doc(name, config) or _ruff_doc(name) or _mypy_doc(name)
    return found or _route_doc(identifier)


def _project_rule_doc(identifier: str, config: Config) -> str | None:
    """Return what the project's rule_doc_command prints for identifier, if it knows it."""
    tokens = {"{python}": sys.executable, "{identifier}": identifier}
    command = [tokens.get(argument, argument) for argument in config.rule_doc_command or ()]
    try:
        result = subprocess.run(
            command, cwd=config.root, capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    return result.stdout if result.returncode == 0 and result.stdout.strip() else None


def _check_doc(check: ProjectCheck, config: Config) -> str:
    """Return a project check's page: what it requires, how it runs, and its own documentation."""
    lines = [f"# {check.name}, a project check", "", check.description, ""]
    lines.append(f"Run as: {' '.join(check.command)}")
    if check.paths is not None:
        lines.append(f"Watches: {', '.join(check.paths)}")
    if check.diff_command is not None:
        lines.append(f"In a diff run: {' '.join(check.diff_command)}")
    if not check.in_diff:
        lines.append("In a diff run: not run; the full run checks it")
    lines.append(f"Documented in: {check.doc}")
    body = doc_text(config.root / check.doc)
    if body:
        lines.extend(["", body])
    return "\n".join(lines) + "\n"


def doc_text(path: Path) -> str:
    """Return the part of a check's doc file that documents it.

    That is a Python file's module docstring, a shell script's leading comment block, or else the
    whole file.
    """
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".py":
        try:
            docstring = ast.get_docstring(ast.parse(text))
        except SyntaxError:
            docstring = None
        if docstring:
            return docstring.strip()
    elif path.suffix in {".sh", ".bash"} or text.startswith("#!"):
        comment = _leading_comment(text)
        if comment:
            return comment
    return text.strip()


def _leading_comment(text: str) -> str:
    block: list[str] = []
    for line in text.splitlines():
        if line.startswith("#!") and not block:
            continue
        if not line.startswith("#"):
            break
        block.append(line[1:].removeprefix(" "))
    return "\n".join(block).strip()


def _pylint_definitions(name: str, config: Config) -> list[tuple[str, str, str]]:
    from pylint.exceptions import UnknownMessageError  # deferred: Pylint is slow to import
    from pylint.lint import PyLinter

    linter = PyLinter()
    linter.load_default_plugins()
    linter.load_plugin_modules([BUNDLED_PLUGIN, *config.pylint_plugins])
    try:
        definitions = linter.msgs_store.get_message_definitions(name)
    except UnknownMessageError:
        return []
    return [(d.symbol, d.msgid, d.description) for d in definitions]


def _pylint_symbol(name: str, config: Config) -> str | None:
    definitions = _pylint_definitions(name, config)
    return definitions[0][0] if definitions else None


def _pylint_doc(name: str, config: Config) -> str | None:
    definitions = _pylint_definitions(name, config)
    if not definitions:
        return None
    symbol, msgid, description = definitions[0]
    return f"# {symbol} ({msgid}), Pylint\n\n{description}\n"


def _ruff_doc(name: str) -> str | None:
    if not re.fullmatch(r"[A-Z]+[0-9]+", name):
        return None
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "rule", name],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


def _mypy_doc(name: str) -> str | None:
    from mypy import errorcodes  # deferred: mypy is only needed for its own codes

    code = errorcodes.error_codes.get(name)
    if code is None:
        return None
    return (
        f"# {code.code}, mypy error code\n\n{code.description}.\n\n"
        "This is the description mypy ships with its installed copy; mypy has no fuller "
        "documentation offline.\n"
    )


def check_docs(config: Config, defences: list[Defence]) -> list[Finding]:
    """Report every bundled or project defence whose page is missing or incomplete.

    Identifiers from Pylint's, Ruff's and mypy's own catalogues are listed from those catalogues,
    so they resolve by construction.
    """
    findings: list[Finding] = []
    for defence in defences:
        if defence.origin not in {"bundled", "project"}:
            continue
        if defence.tool == "check":
            findings.extend(_check_doc_findings(defence, config))
            continue
        directory = BUNDLED_DOCS if defence.origin == "bundled" else config.root / config.docs_dir
        page = directory / f"{defence.identifier}.md"
        display = (
            f"{config.docs_dir}/{page.name}" if defence.origin == "project" else page.as_posix()
        )
        if not page.is_file():
            findings.append(
                Finding(display, 0, DANGLING, f"{defence.identifier} has no documentation page")
            )
            continue
        missing = missing_sections(page.read_text(encoding="utf-8"))
        if missing:
            findings.append(
                Finding(
                    display,
                    0,
                    DANGLING,
                    f"{defence.identifier}'s page lacks: {', '.join(missing)}",
                )
            )
    return findings


def _check_doc_findings(defence: Defence, config: Config) -> list[Finding]:
    check = next(check for check in config.checks if check.name == defence.identifier)
    path = config.root / check.doc
    if not path.is_file():
        message = f"{check.name}'s doc {check.doc} does not exist"
    elif not doc_text(path):
        message = f"{check.name}'s doc {check.doc} is empty"
    else:
        return []
    return [Finding(check.doc, 0, DANGLING, message)]


# What each configuration or comment route silences, for the identifiers the suppression lane
# prints that name a setting rather than a rule.
_ROUTES = {
    "ruff::exclude": "A Ruff `exclude` or `extend-exclude` setting: files Ruff does not check.",
    "mypy::exclude": "A mypy `exclude` setting: files mypy does not check.",
    "mypy::follow_imports": "A mypy `follow_imports = skip` or `silent` setting: imported "
    "modules mypy does not analyse, or analyses without reporting their errors.",
    "mypy::ignore_errors": "A mypy `ignore_errors = true` setting: every error in the modules "
    "it names is dropped.",
    "coverage::no-cover": "A coverage.py `pragma: no cover` comment: the line, or the block it "
    "opens, is left out of measurement.",
    "coverage::no-branch": "A coverage.py `pragma: no branch` comment: a branch not taken there "
    "is not reported as partial.",
    "coverage::omit": "A coverage.py `omit` setting: files left out of measurement.",
    "coverage::exclude_lines": "A coverage.py `exclude_lines` setting: lines matching its "
    "patterns are left out of measurement.",
    "coverage::exclude_also": "A coverage.py `exclude_also` setting: lines matching its patterns "
    "are left out of measurement, beside the default ones.",
    "coverage::partial_branches": "A coverage.py `partial_branches` setting: branches on lines "
    "matching its patterns are not reported as partial.",
}
_UNROUTED_TOOLS = {"bandit": "Bandit", "semgrep": "Semgrep", "pyright": "Pyright"}


def _route_doc(identifier: str) -> str | None:
    """Return a page for an identifier that names a suppression route rather than a rule."""
    tool, _, name = identifier.partition("::")
    what = _ROUTES.get(identifier)
    if what is None and tool == "mypy":
        help_text = _mypy_option_help(name)
        what = f"The mypy setting `{name}`: {help_text}." if help_text else None
    if what is None and tool in _UNROUTED_TOOLS and name:
        label = _UNROUTED_TOOLS[tool]
        what = (
            f"The {label} identifier `{name}`. {label} is not installed with py-qa and py-qa "
            f"does not run it, so its documentation is not available offline; {label}'s own "
            "documentation describes it."
        )
    if what is None:
        return None
    return (
        f"# {identifier}\n\n{what}\n\nThis identifier names a suppression route, not a rule. "
        "py-qa holds every use of it to the project record: a use without an exception for "
        "this identifier and that file is reported as pyqaci.suppression.unrecorded "
        "(`py-qa rule-doc pyqaci.suppression.unrecorded`).\n"
    )


def _mypy_option_help(name: str) -> str | None:
    """Return mypy's own help for a setting, by its configuration or command-line name.

    The help is read from mypy's printed usage, where each option starts a line and an
    `(inverse: --flag)` note names the spelling that turns it the other way.
    """
    from mypy.main import define_options  # deferred: mypy is only needed for its own options

    entries: dict[str, str] = {}
    current: list[str] = []
    text: list[str] = []
    for line in define_options()[0].format_help().splitlines():
        if match := re.match(r"^  (--[a-z][a-z-]*)(?:\s+\S.*)?$", line):
            current, text = [match.group(1)], [line[2 + len(match.group(1)) :]]
            entries[match.group(1)] = ""
        elif current and line.startswith("    "):
            text.append(line)
        else:
            current = []
            continue
        flat = " ".join(" ".join(text).split())
        flat = re.sub(r"(\w)- (\w)", r"\1-\2", flat)
        inverse = re.search(r"\(inverse: (--[a-z-]+)\)", flat)
        described = re.sub(r"\s*\(inverse: [^)]*\)", "", flat).strip()
        entries[current[0]] = described
        if inverse:
            entries[inverse.group(1)] = f"the inverse of `{current[0]}`, which is: {described}"
    flag = "--" + name.replace("_", "-")
    return entries.get(flag) or None
