"""Tests for resolving identifiers to documentation offline, and for the dangling-docs check."""

from pathlib import Path

import pytest

from py_qa.config import load_config
from py_qa.defences import Defence
from py_qa.docs import BUNDLED_DOCS, REQUIRED_SECTIONS, check_docs, missing_sections, resolve
from py_qa.pylint_plugin import BUNDLED_MESSAGES


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    return tmp_path


def test_bundled_page(root: Path) -> None:
    text = resolve("pyqaci.suppression.unrecorded", load_config(root))
    assert text is not None
    assert text.startswith("# pyqaci.suppression.unrecorded")


def test_bundled_pylint_page_by_symbol_msgid_and_prefixed(root: Path) -> None:
    config = load_config(root)
    by_symbol = resolve("pyqaci-sensitive-repr", config)
    assert by_symbol is not None
    assert by_symbol.startswith("# pyqaci-sensitive-repr")
    assert resolve("W9701", config) == by_symbol
    assert resolve("pylint::pyqaci-sensitive-repr", config) == by_symbol


def test_project_page_wins_for_the_projects_own_identifier(root: Path) -> None:
    pages = root / "docs" / "defences"
    pages.mkdir(parents=True)
    (pages / "proj-no-eval.md").write_text("# proj-no-eval\n", encoding="utf-8")
    assert resolve("proj-no-eval", load_config(root)) == "# proj-no-eval\n"


def test_native_catalogues(root: Path) -> None:
    config = load_config(root)
    ruff = resolve("F401", config)
    assert ruff is not None
    assert "unused-import" in ruff
    assert resolve("ruff::F401", config) == ruff
    pylint = resolve("unspecified-encoding", config)
    assert pylint is not None
    assert "W1514" in pylint
    mypy = resolve("arg-type", config)
    assert mypy is not None
    assert "Check argument types in calls" in mypy


def test_unknown_identifier(root: Path) -> None:
    assert resolve("no-such-thing", load_config(root)) is None


def test_every_bundled_identifier_has_a_complete_page() -> None:
    from py_qa.defences import BUILTIN

    for identifier in (*BUILTIN, *BUNDLED_MESSAGES):
        page = BUNDLED_DOCS / f"{identifier}.md"
        assert page.is_file(), identifier
        assert missing_sections(page.read_text(encoding="utf-8")) == [], identifier


def test_every_bundled_page_belongs_to_an_identifier() -> None:
    from py_qa.defences import BUILTIN

    known = {*BUILTIN, *BUNDLED_MESSAGES}
    assert {page.stem for page in BUNDLED_DOCS.glob("*.md")} == known


def test_missing_sections() -> None:
    assert missing_sections("# x\n## What it flags\n") == list(REQUIRED_SECTIONS[1:])


def test_check_docs_reports_project_rules_without_a_page(root: Path) -> None:
    pages = root / "docs" / "defences"
    pages.mkdir(parents=True)
    (pages / "proj-half.md").write_text("# proj-half\n## What it flags\n", encoding="utf-8")
    defences = [
        Defence("proj-none", "pylint", "project", "s"),
        Defence("proj-half", "pylint", "project", "s"),
        Defence("F401", "ruff", "ruff", "s"),
        Defence("pyqaci.tests", "py-qa", "bundled", "s"),
    ]
    rendered = [f.render() for f in check_docs(load_config(root), defences)]
    assert rendered == [
        "docs/defences/proj-none.md: pyqaci.docs.dangling proj-none has no documentation page",
        "docs/defences/proj-half.md: pyqaci.docs.dangling proj-half's page lacks: "
        "## Why, ## How to fix correctly",
    ]


@pytest.mark.parametrize(
    ("identifier", "fragments"),
    [
        (
            "mypy::disallow_untyped_defs",
            ("# mypy::disallow_untyped_defs", "Disallow defining functions without type"),
        ),
        ("mypy::ignore_missing_imports", ("Silently ignore imports of missing modules",)),
        ("bandit::B404", ("# bandit::B404", "Bandit", "not installed with py-qa")),
        ("coverage::no-cover", ("# coverage::no-cover", "coverage.py", "pragma: no cover")),
        ("ruff::exclude", ("# ruff::exclude", "files Ruff does not check")),
        ("semgrep::python.lang.rule", ("# semgrep::python.lang.rule", "Semgrep")),
    ],
)
def test_a_suppression_route_identifier_resolves(
    root: Path, identifier: str, fragments: tuple[str, ...]
) -> None:
    text = resolve(identifier, load_config(root))
    assert text is not None
    for fragment in fragments:
        assert fragment in text
    assert "pyqaci.suppression.unrecorded" in text


def test_an_unknown_route_of_a_known_tool_does_not_resolve(root: Path) -> None:
    assert resolve("mypy::no_such_flag", load_config(root)) is None


CHECK = """
[[tool.py-qa.check]]
name = "spelling"
command = ["{python}", "scripts/spelling.py", "--json"]
description = "Prose is in British English."
doc = "scripts/spelling.py"
paths = ["**/*.md"]
"""


def test_a_project_check_resolves_to_its_description_and_its_docs(root: Path) -> None:
    (root / "pyproject.toml").write_text(CHECK, encoding="utf-8")
    (root / "scripts").mkdir()
    (root / "scripts" / "spelling.py").write_text(
        '"""Check every markdown file for American spellings.\n\nExit 1 on a finding."""\n\nX = 1\n',
        encoding="utf-8",
    )
    text = resolve("spelling", load_config(root))
    assert text is not None
    assert text.startswith("# spelling, a project check\n\nProse is in British English.\n")
    assert "Run as: {python} scripts/spelling.py --json" in text
    assert "Watches: **/*.md" in text
    assert "Check every markdown file for American spellings.\n\nExit 1 on a finding." in text
    assert "X = 1" not in text


@pytest.mark.parametrize(
    ("name", "content", "shown", "hidden"),
    [
        ("check.md", "# Spelling\n\nAll of it.\n", "# Spelling\n\nAll of it.", None),
        (
            "check.sh",
            "#!/bin/bash\n# Checks spelling.\n#\n# Exit 1.\nset -e\n",
            "Checks spelling.\n\nExit 1.",
            "set -e",
        ),
        ("check.py", "X = 1\n", "X = 1", None),
        ("check.txt", "plain words\n", "plain words", None),
    ],
)
def test_a_check_doc_shows_what_documents_it(
    root: Path, name: str, content: str, shown: str, hidden: str | None
) -> None:
    pyproject = CHECK.replace('doc = "scripts/spelling.py"', f'doc = "{name}"')
    (root / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    (root / name).write_text(content, encoding="utf-8")
    text = resolve("spelling", load_config(root))
    assert text is not None
    assert shown in text
    if hidden is not None:
        assert hidden not in text


def test_check_docs_reports_a_project_check_whose_doc_is_missing_or_empty(root: Path) -> None:
    (root / "pyproject.toml").write_text(CHECK, encoding="utf-8")
    config = load_config(root)
    defences = [Defence("spelling", "check", "project", "Prose is in British English.")]
    (finding,) = check_docs(config, defences)
    assert finding.path == "scripts/spelling.py"
    assert "spelling's doc scripts/spelling.py does not exist" in finding.message
    (root / "scripts").mkdir()
    (root / "scripts" / "spelling.py").write_text("\n", encoding="utf-8")
    (finding,) = check_docs(config, defences)
    assert "is empty" in finding.message
    (root / "scripts" / "spelling.py").write_text('"""Spelling."""\n', encoding="utf-8")
    assert check_docs(config, defences) == []


def test_rule_doc_command_resolves_what_nothing_else_does(root: Path) -> None:
    (root / "explain.py").write_text(
        "import sys\nif sys.argv[1] == 'known-id':\n    print('known-id: what it means')\n"
        "else:\n    sys.exit(1)\n",
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text(
        '[tool.py-qa]\nrule_doc_command = ["{python}", "explain.py", "{identifier}"]\n',
        encoding="utf-8",
    )
    config = load_config(root)
    assert resolve("known-id", config) == "known-id: what it means\n"
    assert resolve("unknown-id", config) is None
    assert resolve("pyqaci.tests", config) is not None
