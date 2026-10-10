"""Resolving any printed identifier to its documentation, offline, and the dangling-docs check."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from py_qa.finding import Finding
from py_qa.tools import BUNDLED_PLUGIN

if TYPE_CHECKING:
    from py_qa.config import Config
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

    The order is the bundled pages, the project's own pages under docs_dir, then the catalogues
    Pylint, Ruff and mypy ship with their installed copies.
    """
    name = _PREFIX.sub("", identifier)
    symbol = _pylint_symbol(name, config) or name
    for directory in (BUNDLED_DOCS, config.root / config.docs_dir):
        for candidate in (name, symbol):
            page = directory / f"{candidate}.md"
            if page.is_file():
                return page.read_text(encoding="utf-8")
    return _pylint_doc(name, config) or _ruff_doc(name) or _mypy_doc(name)


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
