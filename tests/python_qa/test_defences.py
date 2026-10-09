"""Tests for the listing of active defences, derived from the configuration in force."""

from pathlib import Path

from python_qa.config import load_config
from python_qa.defences import BUILTIN, active_defences

PLUGIN = '''"""A project's own Pylint rule, for the listing to find."""
from pylint.checkers import BaseChecker


class NoEvalChecker(BaseChecker):
    name = "proj-no-eval"
    msgs = {"W9901": ("eval used", "proj-no-eval", "Do not call eval. Parse the input instead.")}


def register(linter):
    linter.register_checker(NoEvalChecker(linter))
'''


def setup(root: Path, table: str) -> None:
    (root / "pyproject.toml").write_text(table, encoding="utf-8")


def test_lists_builtins_bundled_project_ruff_and_mypy(tmp_path: Path) -> None:
    setup(
        tmp_path,
        '[tool.python-qa]\npylint_plugins = ["proj_rules"]\n'
        '[tool.python-qa.summary]\nfile = "AGENTS.md"\n'
        '[tool.ruff.lint]\nselect = ["F401"]\n',
    )
    (tmp_path / "proj_rules.py").write_text(PLUGIN, encoding="utf-8")
    defences = {d.identifier: d for d in active_defences(load_config(tmp_path))}
    assert defences["pyqaci.suppression.unrecorded"].origin == "bundled"
    assert defences["pyqaci.summary.stale"].tool == "python-qa"
    assert defences["pyqaci-sensitive-repr"].tool == "pylint"
    assert defences["pyqaci-sensitive-repr"].origin == "bundled"
    assert defences["proj-no-eval"].origin == "project"
    assert defences["proj-no-eval"].summary == "Do not call eval."
    assert defences["F401"].tool == "ruff"
    assert defences["arg-type"].tool == "mypy"
    assert all(d.doc == f"python-qa rule-doc {d.identifier}" for d in defences.values())


def test_switched_off_lanes_are_not_listed(tmp_path: Path) -> None:
    setup(
        tmp_path,
        "[tool.python-qa.tools]\nruff = false\nmypy = false\npylint = false\nsuppression = false\n",
    )
    identifiers = {d.identifier for d in active_defences(load_config(tmp_path))}
    assert "pyqaci-sensitive-repr" not in identifiers
    assert "pyqaci.suppression.unrecorded" not in identifiers
    assert "pyqaci.summary.stale" not in identifiers
    assert "pyqaci.record.invalid" in identifiers
    assert not any(identifier.startswith("F") for identifier in identifiers)


def test_every_builtin_names_its_lane_and_summary() -> None:
    for identifier, (lane, summary) in BUILTIN.items():
        assert identifier.startswith("pyqaci.")
        assert lane
        assert summary.endswith(".")
