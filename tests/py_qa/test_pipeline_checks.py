"""Tests for project checks, the test lane's setup, diff runs and the JSON report."""

import io
import json
import sys
from datetime import date
from pathlib import Path

import pytest

from py_qa.config import load_config
from py_qa.diff import Change
from py_qa.pipeline import UsageError, all_lanes, run_pipeline, run_subprocess

TODAY = date(2026, 3, 1)
PYTHON = sys.executable
CHECKS = """
[[tool.py-qa.check]]
name = "spelling"
command = ["{python}", "scripts/spelling.py"]
description = "Prose is in British English."
doc = "scripts/spelling.py"
paths = ["**/*.md"]
diff_command = ["{python}", "scripts/spelling.py", "{files}"]

[[tool.py-qa.check]]
name = "history"
command = ["scripts/history.sh"]
description = "No commit carries a secret."
doc = "scripts/history.sh"
diff = false

[[tool.py-qa.check]]
name = "smoke"
command = ["scripts/smoke.sh", "{python}"]
description = "The installed command answers."
doc = "scripts/smoke.sh"
phase = "runners"
"""


class Recorder:
    """Records each command, and fails those containing any of the given arguments."""

    def __init__(self, failing: tuple[str, ...] = ()) -> None:
        self.failing = failing
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str], cwd: Path) -> int:
        assert cwd.is_dir()
        self.calls.append(command)
        return 1 if set(self.failing) & set(command) else 0

    def named(self, word: str) -> list[list[str]]:
        return [command for command in self.calls if word in " ".join(command)]


def project(tmp_path: Path, extra: str = "") -> Path:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.py-qa.tools]\nsummary = false\ndocs = false\ncoverage = false\n" + extra,
        encoding="utf-8",
    )
    for name, text in {
        "src/pkg/__init__.py": "",
        "src/pkg/a.py": "A = 1\n",
        "src/pkg/b.py": "B = 2\n",
        "tests/test_a.py": "import pkg.a\n",
        "tests/test_b.py": "import pkg.b\n",
        "docs/guide.md": "# Guide\n",
        "scripts/spelling.py": "",
    }.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def run(
    root: Path,
    runner: Recorder,
    *,
    requested: tuple[str, ...] = (),
    change: Change | None = None,
    report: Path | None = None,
) -> tuple[int, str]:
    out = io.StringIO()
    code = run_pipeline(
        load_config(root),
        requested=requested,
        paths=None,
        no_fix=True,
        fail_fast=False,
        out=out,
        runner=runner,
        today=TODAY,
        change=change,
        report=report,
    )
    return code, out.getvalue()


def change(*files: str, deleted: tuple[str, ...] = ()) -> Change:
    return Change("main", "a" * 40, files, deleted)


def test_project_checks_run_in_their_phase_in_declared_order(tmp_path: Path) -> None:
    root = project(tmp_path, CHECKS)
    config = load_config(root)
    lanes = all_lanes(config)
    assert lanes.index("pylint") < lanes.index("spelling") < lanes.index("history")
    assert lanes.index("test") < lanes.index("smoke") < lanes.index("audit")
    runner = Recorder()
    code, _ = run(root, runner)
    assert code == 0
    assert runner.named("spelling.py") == [[PYTHON, "scripts/spelling.py"]]
    assert runner.named("smoke.sh") == [["scripts/smoke.sh", PYTHON]]


def test_a_failing_check_names_its_identifier_and_stops_the_runners(tmp_path: Path) -> None:
    root = project(tmp_path, CHECKS)
    runner = Recorder(failing=("scripts/history.sh",))
    code, output = run(root, runner)
    assert code == 1
    assert "py-qa: history failed: history (py-qa rule-doc history)" in output
    assert runner.named("smoke.sh") == []
    assert "runners not run" in output


def test_a_check_can_be_run_alone(tmp_path: Path) -> None:
    root = project(tmp_path, CHECKS)
    runner = Recorder()
    code, _ = run(root, runner, requested=("smoke",))
    assert code == 0
    assert runner.calls == [["scripts/smoke.sh", PYTHON]]


def test_test_setup_runs_first_and_its_failure_fails_the_lane(tmp_path: Path) -> None:
    root = project(tmp_path, '[tool.py-qa.test]\nsetup = [["scripts/start.sh"]]\n')
    runner = Recorder()
    assert run(root, runner, requested=("test",))[0] == 0
    assert runner.calls == [["scripts/start.sh"], [PYTHON, "-m", "pytest"]]
    failing = Recorder(failing=("scripts/start.sh",))
    code, output = run(root, failing, requested=("test",))
    assert code == 1
    assert failing.calls == [["scripts/start.sh"]]
    assert "py-qa: test setup failed: scripts/start.sh" in output


def test_a_command_that_cannot_start_fails_with_the_shells_status(tmp_path: Path) -> None:
    assert run_subprocess([str(tmp_path / "missing")], tmp_path) == 127


def test_a_diff_run_narrows_source_lanes_to_the_changed_files(tmp_path: Path) -> None:
    root = project(tmp_path)
    runner = Recorder()
    code, output = run(
        root,
        runner,
        requested=("fmt", "ruff", "mypy", "pylint"),
        change=change("src/pkg/a.py", "docs/guide.md"),
    )
    assert code == 0
    assert "diff run against main (merge base aaaaaaaaaaaa): 2 changed files" in output
    for lane in ("format", "check", "pylint"):
        commands = runner.named(lane)
        assert commands, lane
        assert all(command[-1] == "src/pkg/a.py" for command in commands), lane
    (mypy,) = runner.named("mypy")
    assert mypy[-2:] == ["src", "tests"]


def test_a_diff_run_with_no_python_change_checks_no_source(tmp_path: Path) -> None:
    root = project(tmp_path)
    runner = Recorder()
    code, output = run(root, runner, requested=("ruff",), change=change("docs/guide.md"))
    assert code == 0
    assert runner.calls == []
    assert "py-qa: ruff: nothing to check within this lane's paths" in output


def test_a_diff_run_runs_a_check_only_when_a_file_it_watches_changed(tmp_path: Path) -> None:
    root = project(tmp_path, CHECKS)
    runner = Recorder()
    code, output = run(
        root, runner, requested=("spelling", "history"), change=change("src/pkg/a.py")
    )
    assert code == 0
    assert runner.calls == []
    assert "py-qa: spelling: no change to the files it checks" in output
    assert "py-qa: history: runs in the full run only" in output
    runner = Recorder()
    run(root, runner, requested=("spelling",), change=change("docs/guide.md", deleted=("x.md",)))
    assert runner.calls == [[PYTHON, "scripts/spelling.py", "docs/guide.md"]]


def test_a_diff_run_tests_only_what_the_change_reaches(tmp_path: Path) -> None:
    root = project(tmp_path)
    runner = Recorder()
    code, output = run(root, runner, requested=("test",), change=change("src/pkg/a.py"))
    assert code == 0
    assert runner.calls == [[PYTHON, "-m", "pytest", "tests/test_a.py"]]
    assert "py-qa: test: 1 affected test file" in output


def test_a_diff_run_with_no_affected_test_passes_and_says_why(tmp_path: Path) -> None:
    root = project(tmp_path, '[tool.py-qa.diff]\nunmapped = "ignore"\n')
    runner = Recorder()
    code, output = run(root, runner, requested=("test",), change=change("docs/guide.md"))
    assert code == 0
    assert runner.calls == []
    assert "py-qa: test: docs/guide.md: no test is known to read it" in output
    assert "py-qa: test: no test can be affected by the change" in output


def test_a_diff_run_that_needs_every_test_runs_the_full_lane(tmp_path: Path) -> None:
    root = project(tmp_path)
    runner = Recorder()
    code, output = run(root, runner, requested=("test",), change=change("docs/guide.md"))
    assert code == 0
    assert runner.calls == [[PYTHON, "-m", "pytest"]]
    assert "every test runs: docs/guide.md: no test is known to read it" in output


def test_a_diff_run_uses_the_projects_diff_command(tmp_path: Path) -> None:
    root = project(
        tmp_path,
        '[tool.py-qa.test]\ncommand = ["scripts/test.sh"]\n'
        'diff_command = ["scripts/test.sh", "--base", "{base}", "--", "{tests}"]\n',
    )
    runner = Recorder()
    run(root, runner, requested=("test",), change=change("src/pkg/b.py"))
    assert runner.calls == [["scripts/test.sh", "--base", "main", "--", "tests/test_b.py"]]


def test_a_test_command_with_no_diff_command_runs_whole(tmp_path: Path) -> None:
    root = project(tmp_path, '[tool.py-qa.test]\ncommand = ["scripts/test.sh"]\n')
    runner = Recorder()
    _, output = run(root, runner, requested=("test",), change=change("src/pkg/b.py"))
    assert runner.calls == [["scripts/test.sh"]]
    assert "takes no test list, so it runs whole" in output


def test_a_diff_map_naming_a_missing_test_fails_the_lane(tmp_path: Path) -> None:
    root = project(tmp_path, '[[tool.py-qa.diff.map]]\nglob = "*.md"\ntests = ["tests/gone.py"]\n')
    runner = Recorder()
    code, output = run(root, runner, requested=("test",), change=change("docs/guide.md"))
    assert code == 1
    assert runner.calls == []
    assert "tests/gone.py is named by [[tool.py-qa.diff.map]] and does not exist" in output


def test_paths_and_a_diff_together_are_a_usage_error(tmp_path: Path) -> None:
    with pytest.raises(UsageError, match="-p and --diff"):
        run_pipeline(
            load_config(project(tmp_path)),
            requested=(),
            paths=("src",),
            no_fix=True,
            fail_fast=False,
            out=io.StringIO(),
            runner=Recorder(),
            today=TODAY,
            change=change("src/pkg/a.py"),
        )


def test_the_json_report_holds_every_lane_and_the_selection(tmp_path: Path) -> None:
    root = project(tmp_path, CHECKS)
    report = tmp_path / "out" / "qa.json"
    code, _ = run(root, Recorder(), change=change("src/pkg/a.py"), report=report)
    data = json.loads(report.read_text(encoding="utf-8"))
    assert code == 0
    assert data["result"] == "PASS"
    assert data["mode"] == "diff"
    assert data["diff"]["changed"] == ["src/pkg/a.py"]
    lanes = {lane["name"]: lane for lane in data["lanes"]}
    assert lanes["spelling"]["status"] == "skip"
    assert lanes["spelling"]["phase"] == "detectors"
    assert lanes["smoke"]["status"] == "PASS"
    assert lanes["docs"]["status"] == "off"
    assert data["tests"]["selected"] == ["tests/test_a.py"]
    assert data["tests"]["reached_by"] == {"tests/test_a.py": ["src/pkg/a.py"]}


def test_the_json_report_of_a_full_run(tmp_path: Path) -> None:
    root = project(tmp_path)
    report = tmp_path / "qa.json"
    code, _ = run(root, Recorder(failing=("mypy",)), report=report)
    data = json.loads(report.read_text(encoding="utf-8"))
    assert code == 1
    assert data["result"] == "FAIL"
    assert data["mode"] == "full"
    assert "tests" not in data
    statuses = {lane["name"]: lane["status"] for lane in data["lanes"]}
    assert statuses["mypy"] == "FAIL"
    assert statuses["test"] == "not run"
