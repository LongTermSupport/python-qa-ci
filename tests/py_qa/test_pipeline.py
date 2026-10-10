"""Tests for the pipeline: lane selection, phase order, and stopping before runners."""

import io
import re
from datetime import date
from pathlib import Path

import pytest

from py_qa.config import load_config
from py_qa.pipeline import LANES, METHOD_LINE, UsageError, run_pipeline

TODAY = date(2026, 3, 1)


class FakeRunner:
    """Records each command and fails the ones whose module is listed."""

    def __init__(self, failing: tuple[str, ...] = ()) -> None:
        self.failing = failing
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str], cwd: Path) -> int:
        assert cwd.is_dir()
        self.calls.append(command)
        return 1 if (command[2] if len(command) > 2 else command[-1]) in self.failing else 0

    def modules(self) -> list[str]:
        return [command[2] if command[2] != "coverage" else command[3] for command in self.calls]


def project(tmp_path: Path, extra: str = "") -> Path:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.py-qa.tools]\nsummary = false\ndocs = false\n" + extra, encoding="utf-8"
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "ok.py").write_text("x = 1\n", encoding="utf-8")
    return tmp_path


def run(
    root: Path,
    runner: FakeRunner,
    *,
    requested: tuple[str, ...] = (),
    paths: tuple[str, ...] | None = None,
    fail_fast: bool = False,
) -> tuple[int, str]:
    out = io.StringIO()
    code = run_pipeline(
        load_config(root),
        requested=requested,
        paths=paths,
        no_fix=True,
        fail_fast=fail_fast,
        out=out,
        runner=runner,
        today=TODAY,
    )
    return code, out.getvalue()


def test_clean_run_runs_every_lane_in_phase_order(tmp_path: Path) -> None:
    runner = FakeRunner()
    code, output = run(project(tmp_path), runner)
    assert code == 0
    assert runner.modules() == ["ruff", "ruff", "mypy", "pylint", "run", "report"]
    assert METHOD_LINE not in output
    assert "PASS" in output


def test_detector_failure_stops_before_runners_but_every_detector_runs(tmp_path: Path) -> None:
    runner = FakeRunner(failing=("mypy",))
    code, output = run(project(tmp_path), runner)
    assert code == 1
    assert runner.modules() == ["ruff", "ruff", "mypy", "pylint"]
    assert "runners not run: a format or detector lane failed" in output
    assert METHOD_LINE in output


def test_fail_fast_stops_at_the_first_failure(tmp_path: Path) -> None:
    runner = FakeRunner(failing=("ruff",))
    code, _ = run(project(tmp_path), runner, fail_fast=True)
    assert code == 1
    assert runner.modules() == ["ruff"]


def test_builtin_findings_fail_the_suppression_lane(tmp_path: Path) -> None:
    root = project(tmp_path)
    (root / "src" / "bad.py").write_text("x = 1  # " + "noqa\n", encoding="utf-8")
    runner = FakeRunner()
    code, output = run(root, runner, requested=("suppression",))
    assert code == 1
    assert "src/bad.py:1: pyqaci.suppression.blanket" in output
    assert runner.calls == []


def test_unreadable_file_is_reported_not_skipped(tmp_path: Path) -> None:
    root = project(tmp_path)
    (root / "src" / "broken.py").write_text('x = """\n', encoding="utf-8")
    code, output = run(root, FakeRunner(), requested=("suppression",))
    assert code == 1
    assert "src/broken.py: pyqaci.suppression.unscanned" in output


def test_lane_failure_without_native_identifier_prints_one(tmp_path: Path) -> None:
    runner = FakeRunner(failing=("coverage",))
    code, output = run(project(tmp_path), runner, requested=("test",))
    assert code == 1
    assert "pyqaci.tests" in output
    assert "py-qa rule-doc pyqaci.tests" in output


def test_paths_limit_detectors_and_skip_runners(tmp_path: Path) -> None:
    runner = FakeRunner()
    code, output = run(project(tmp_path), runner, paths=("src/ok.py",))
    assert code == 0
    assert all("src/ok.py" in command for command in runner.calls)
    assert "runners not run: -p limits the run to format and detectors" in output


def test_switched_off_lane_is_reported_as_skipped(tmp_path: Path) -> None:
    root = project(tmp_path, "mypy = false\n")
    runner = FakeRunner()
    _, output = run(root, runner)
    assert "mypy" not in runner.modules()
    assert "mypy" in output
    assert "off" in output


def test_unknown_lane_is_a_usage_error(tmp_path: Path) -> None:
    with pytest.raises(UsageError, match="nope"):
        run(project(tmp_path), FakeRunner(), requested=("nope",))


def test_lanes_cover_every_switch_except_coverage() -> None:
    from py_qa.config import TOOLS

    assert set(LANES) == set(TOOLS) - {"coverage"}


class Clock:
    """A monotonic clock that advances 1.5 seconds each time it is read."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 1.5
        return self.now


def test_summary_table_shows_each_lanes_duration(tmp_path: Path) -> None:
    out = io.StringIO()
    run_pipeline(
        load_config(project(tmp_path)),
        requested=("record", "mypy"),
        paths=None,
        no_fix=True,
        fail_fast=False,
        out=out,
        runner=FakeRunner(),
        today=TODAY,
        clock=Clock(),
    )
    table = out.getvalue()
    assert "PASS     record          1.5s" in table
    assert "PASS     mypy            1.5s" in table
    assert re.search(r"^ +total +7\.5s$", table, re.MULTILINE)


def test_test_command_runs_in_place_of_pytest(tmp_path: Path) -> None:
    root = project(tmp_path, '[tool.py-qa.test]\ncommand = ["scripts/qa.sh", "tests"]\n')
    runner = FakeRunner(failing=("tests",))
    code, output = run(root, runner, requested=("test",))
    assert code == 1
    assert runner.calls == [["scripts/qa.sh", "tests"]]
    assert "py-qa: test failed: pyqaci.tests" in output


def test_a_lane_with_nothing_in_scope_says_so(tmp_path: Path) -> None:
    root = project(tmp_path, '[tool.py-qa.lane_paths]\nmypy = ["src"]\n')
    (root / "tests").mkdir()
    (root / "tests" / "t.py").write_text("x = 1\n", encoding="utf-8")
    runner = FakeRunner()
    code, output = run(root, runner, requested=("mypy",), paths=("tests/t.py",))
    assert code == 0
    assert runner.calls == []
    assert "py-qa: mypy: nothing to check within this lane's paths" in output
