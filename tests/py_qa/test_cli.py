"""Tests for the py-qa command line, through main() as a user would call it."""

import json
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path

import pytest

from py_qa import __version__
from py_qa.cli import main

REASON = (
    "The fixture deliberately holds the construction so the red proof of the rule has a target."
)
TODAY = datetime.now(tz=UTC).date()
LEAKY = "from dataclasses import dataclass\n\n\n@dataclass\nclass Login:\n    password: str\n"


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.py-qa.summary]\nfile = "AGENTS.md"\n', encoding="utf-8"
    )
    (tmp_path / "src").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CI", raising=False)
    return tmp_path


def record(root: Path, rule: str = "ruff::E501", path: str = "src/a.py") -> None:
    (root / "qa").mkdir(exist_ok=True)
    (root / "qa" / "record.toml").write_text(
        f'[[exception]]\nrule = "{rule}"\npath = "{path}"\njustification = "{REASON}"\n'
        f'decided_by = "alice"\ndecided_on = {TODAY - timedelta(days=10)}\n'
        f"review_by = {TODAY + timedelta(days=30)}\n",
        encoding="utf-8",
    )


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_rule_doc_found_and_not_found(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["rule-doc", "pyqaci-broad-suppress"]) == 0
    assert capsys.readouterr().out.startswith("# pyqaci-broad-suppress")
    assert main(["rule-doc", "nothing-here"]) == 1
    assert "no documentation" in capsys.readouterr().err


def test_rules_text_and_json(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    record(root, path="src/a.py")
    assert main(["rules"]) == 0
    text = capsys.readouterr().out
    assert "pyqaci-sensitive-repr" in text
    assert "py-qa rule-doc pyqaci-sensitive-repr" in text
    assert "Project record (qa/record.toml): 1 exception" in text
    assert "ruff::E501  src/a.py" in text
    assert main(["rules", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    identifiers = {d["identifier"] for d in data["defences"]}
    assert {"pyqaci-broad-suppress", "pyqaci.record.invalid", "F401"} <= identifiers
    assert data["record"][0]["rule"] == "ruff::E501"
    assert data["scan_exclude"] == []
    assert data["lane_paths"] == {}


def test_rules_lists_lanes_with_paths_of_their_own(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (root / "pyproject.toml").write_text(
        '[tool.py-qa]\npaths = ["src", "tests"]\n[tool.py-qa.lane_paths]\nmypy = ["src"]\n',
        encoding="utf-8",
    )
    assert main(["rules"]) == 0
    text = capsys.readouterr().out
    assert "Lanes given paths of their own, in place of paths (src, tests):\n  mypy: src\n" in text
    assert main(["rules", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["lane_paths"] == {"mypy": ["src"]}


def test_record_list_and_check(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    record(root)
    assert main(["record", "list"]) == 0
    assert "ruff::E501" in capsys.readouterr().out
    assert main(["record", "check"]) == 0
    record(root, rule="E501")
    assert main(["record", "check"]) == 1
    assert "pyqaci.record.invalid" in capsys.readouterr().out


def test_summary_write_then_check(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["summary", "--check"]) == 1
    assert main(["summary"]) == 0
    assert "pyqaci-sensitive-repr" in (root / "AGENTS.md").read_text(encoding="utf-8")
    assert main(["summary", "--check"]) == 0
    capsys.readouterr()


def test_docs_check_passes_on_bundled_pages(root: Path) -> None:
    assert main(["docs-check"]) == 0


def test_rule_harness_pylint(root: Path, capfd: pytest.CaptureFixture[str]) -> None:
    (root / "src" / "leaky.py").write_text(LEAKY, encoding="utf-8")
    (root / "src" / "clean.py").write_text("x = 1\n", encoding="utf-8")
    assert main(["rule", "pyqaci-sensitive-repr", "src/leaky.py"]) == 1
    assert "pyqaci-sensitive-repr" in capfd.readouterr().out
    assert main(["rule", "pyqaci-sensitive-repr", "src/clean.py"]) == 0


def test_rule_harness_ruff_and_builtin(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (root / "src" / "a.py").write_text("import os\nx = 1  # " + "noqa\n", encoding="utf-8")
    assert main(["rule", "F401", "src/a.py"]) == 1
    assert main(["rule", "pyqaci.suppression.blanket", "src/a.py"]) == 1
    assert "src/a.py:2: pyqaci.suppression.blanket" in capsys.readouterr().out
    assert main(["rule", "pyqaci.suppression.unscanned", "src/a.py"]) == 0


def test_rule_harness_refuses_what_it_cannot_run_alone(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["rule", "arg-type", "src"]) == 2
    assert "cannot run one rule alone" in capsys.readouterr().err


def test_run_selected_lane(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (root / "src" / "a.py").write_text("x = 1  # " + "noqa\n", encoding="utf-8")
    assert main(["run", "-t", "suppression"]) == 1
    assert "pyqaci.suppression.blanket" in capsys.readouterr().out


def test_configuration_error_exits_2(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (root / "pyproject.toml").write_text("[tool.py-qa]\nbad = 1\n", encoding="utf-8")
    assert main(["rules"]) == 2
    assert "unknown key bad" in capsys.readouterr().err


def test_tools_lists_lanes(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["tools"]) == 0
    out = capsys.readouterr().out
    assert "ruff" in out
    assert "audit" in out
    assert "off" in out


def test_tools_names_the_tool_behind_each_lane_not_its_arguments(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["tools"]) == 0
    lanes = {line.split()[0]: line for line in capsys.readouterr().out.splitlines()}
    assert lanes["fmt"].endswith(f"ruff format {version('ruff')}")
    assert lanes["mypy"].endswith(f"mypy {version('mypy')}")
    assert lanes["pylint"].endswith(f"pylint {version('pylint')}")
    assert "pytest" in lanes["test"]
    assert "coverage" in lanes["test"]
    assert "--rcfile" not in lanes["pylint"]
    assert "src" not in lanes["mypy"]
    assert lanes["record"].endswith("py-qa")
