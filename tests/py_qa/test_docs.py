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
