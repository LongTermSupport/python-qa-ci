"""Tests for the py-qa command line, through main() as a user would call it."""

import json
import subprocess
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


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def committed(root: Path) -> None:
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "dev@example.com")
    git(root, "config", "user.name", "Dev")
    git(root, "config", "commit.gpgsign", "false")
    (root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_a.py").write_text("import a\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "base")
    git(root, "checkout", "-q", "-b", "work")


def test_a_diff_run_writes_its_report(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    committed(root)
    (root / "src" / "a.py").write_text("x = 2  # " + "noqa\n", encoding="utf-8")
    assert main(["run", "--base", "main", "-t", "suppression", "--json", "qa.json"]) == 1
    out = capsys.readouterr().out
    assert "diff run against main" in out
    assert "src/a.py:1: pyqaci.suppression.blanket" in out
    data = json.loads((root / "qa.json").read_text(encoding="utf-8"))
    assert data["mode"] == "diff"
    assert data["diff"]["changed"] == ["src/a.py"]


def test_affected_lists_the_tests_and_why(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    committed(root)
    (root / "src" / "a.py").write_text("x = 2\n", encoding="utf-8")
    (root / "notes.txt").write_text("hello\n", encoding="utf-8")
    assert main(["affected", "--base", "main"]) == 0
    out = capsys.readouterr().out
    assert "tests/test_a.py  <-  src/a.py" in out
    assert "Every test runs:\n  notes.txt: no test is known to read it" in out
    assert "No test is known to read:\n  notes.txt" in out
    assert main(["affected", "--base", "main", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["tests"] == {"tests/test_a.py": ["src/a.py"]}
    assert data["full"] is True
    assert data["unmapped"] == ["notes.txt"]


def test_affected_fails_when_the_map_names_a_missing_test(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    committed(root)
    with (root / "pyproject.toml").open("a", encoding="utf-8") as handle:
        handle.write('[[tool.py-qa.diff.map]]\nglob = "*.txt"\ntests = ["tests/gone.py"]\n')
    (root / "notes.txt").write_text("hello\n", encoding="utf-8")
    assert main(["affected", "--base", "main"]) == 1
    assert (
        "Named by [[tool.py-qa.diff.map]] and missing:\n  tests/gone.py" in capsys.readouterr().out
    )
    assert main(["affected", "--base", "main", "--json"]) == 1


def test_an_unknown_base_exits_2(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    committed(root)
    assert main(["run", "--base", "nope"]) == 2
    assert "the base nope is not a commit" in capsys.readouterr().err


def test_a_held_lock_exits_3(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from py_qa.lock import run_lock

    committed(root)
    with run_lock(root / ".git" / "py-qa" / "run.lock"):
        assert main(["run", "-t", "record"]) == 3
        assert "another py-qa run holds" in capsys.readouterr().err
        assert main(["run", "-t", "record", "--no-lock"]) == 0


def test_tools_and_rule_doc_cover_project_checks(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with (root / "pyproject.toml").open("a", encoding="utf-8") as handle:
        handle.write(
            '[[tool.py-qa.check]]\nname = "spelling"\ncommand = ["scripts/spell.sh", "--all"]\n'
            'description = "Prose is in British English."\ndoc = "scripts/spell.sh"\n'
        )
    assert main(["tools"]) == 0
    lanes = {line.split()[0]: line for line in capsys.readouterr().out.splitlines()}
    assert lanes["spelling"].endswith("project check: scripts/spell.sh --all")
    assert main(["rule-doc", "spelling"]) == 0
    assert capsys.readouterr().out.startswith("# spelling, a project check")
