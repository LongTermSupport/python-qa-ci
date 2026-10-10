"""The run: format, then every detector, then the runners, which run only if all before passed.

A full run checks the whole project. `-p` narrows the format and detector lanes to paths and runs
no runner. A diff run narrows every lane to what changed against a base: the format, Ruff and
Pylint lanes to the changed Python files, each project check to whether a file it watches
changed, and the test lane to the tests the change can affect; mypy, which needs the whole
program to judge one file, and py-qa's own lanes, which are quick, still read the whole project.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from py_qa import __version__
from py_qa.affected import Selection, select_tests
from py_qa.defences import Defence, active_defences
from py_qa.docs import check_docs
from py_qa.finding import Finding
from py_qa.globs import match_any
from py_qa.record import RecordEntry, check_record, load_record
from py_qa.summary import check_summary
from py_qa.suppression import (
    UNSCANNED,
    Site,
    check_suppressions,
    comment_sites,
    config_sites,
    project_files,
    scope_files,
    within,
)
from py_qa.tools import format_diff_command, lane_commands, lane_targets, test_commands

if TYPE_CHECKING:
    from datetime import date
    from pathlib import Path
    from typing import TextIO

    from py_qa.config import Config, ProjectCheck
    from py_qa.diff import Change

    Runner = Callable[[list[str], Path], int]

METHOD_LINE = (
    "Defence Before Fix (DBF): https://defence-before-fix.github.io/ - agent prompt: "
    "https://defence-before-fix.github.io/defence-before-fix-project-prompt.md"
)
PHASES = (
    ("format", ("fmt",)),
    ("detectors", ("record", "suppression", "summary", "docs", "ruff", "mypy", "pylint")),
    ("runners", ("test", "audit")),
)
LANES = tuple(lane for _, lanes in PHASES for lane in lanes)
BUILTIN_LANES = frozenset({"record", "suppression", "summary", "docs"})
# Lanes a diff run narrows to the changed Python files.
_DIFF_FILE_LANES = ("fmt", "ruff", "pylint")
# Lanes whose tool prints no identifier of its own: py-qa prints one for each failing step.
_LANE_IDENTIFIERS = {
    "fmt": ("pyqaci.format",),
    "test": ("pyqaci.tests", "pyqaci.coverage"),
    "audit": ("pyqaci.audit",),
}
# The exit status a shell gives a command it cannot run.
_CANNOT_RUN = 127


class UsageError(Exception):
    """The command line asks for something py-qa does not have."""


def run_subprocess(command: list[str], cwd: Path) -> int:
    """Run one tool with its output going straight to the terminal, and return its exit code."""
    try:
        return subprocess.run(command, cwd=cwd, check=False).returncode
    except OSError as error:
        sys.stdout.write(f"py-qa: cannot run {command[0]}: {error}\n")
        return _CANNOT_RUN


def lane_phases(config: Config) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Return the run's phases and their lanes in order, the project's checks among them."""
    detectors = tuple(check.name for check in config.checks if check.phase == "detectors")
    runners = tuple(check.name for check in config.checks if check.phase == "runners")
    return (
        PHASES[0],
        ("detectors", (*PHASES[1][1], *detectors)),
        ("runners", ("test", *runners, "audit")),
    )


def all_lanes(config: Config) -> tuple[str, ...]:
    """Return every lane name, built in and project, in run order."""
    return tuple(lane for _, lanes in lane_phases(config) for lane in lanes)


@dataclass(frozen=True)
class LaneResult:
    """One lane's outcome in the closing table and the JSON report."""

    name: str
    phase: str
    status: str
    seconds: float | None = None
    note: str = ""


@dataclass
class _Run:
    config: Config
    paths: tuple[str, ...] | None
    out: TextIO
    today: date
    clock: Callable[[], float]
    started: float
    runner: Runner
    no_fix: bool
    change: Change | None = None
    selection: Selection | None = None
    entries_cache: tuple[list[RecordEntry], list[Finding]] | None = None
    defences_cache: list[Defence] | None = None
    commands_cache: dict[str, list[list[str]]] | None = None
    results: list[LaneResult] = field(default_factory=list)

    def entries(self) -> tuple[list[RecordEntry], list[Finding]]:
        if self.entries_cache is None:
            self.entries_cache = load_record(
                self.config.record_path,
                self.config.record.path,
                today=self.today,
                max_review_days=self.config.record.max_review_days,
            )
        return self.entries_cache

    def defences(self) -> list[Defence]:
        if self.defences_cache is None:
            self.defences_cache = active_defences(self.config)
        return self.defences_cache

    def builtin(self, lane: str) -> list[Finding]:
        entries, invalid = self.entries()
        if lane == "record":
            return invalid + check_record(
                entries, self.config.record, self.config.record.path, self.today
            )
        if lane == "suppression":
            return suppression_findings(self.config, entries, self.paths)
        if lane == "summary":
            return check_summary(self.config, self.defences(), entries)
        return check_docs(self.config, self.defences())

    def step(self, command: list[str]) -> int:
        self.out.flush()
        return self.runner(command, self.config.root)

    def source_targets(self, lane: str) -> list[str]:
        """Return what a format or detector lane is given: its paths, or the changed files."""
        if self.change is None or lane not in _DIFF_FILE_LANES:
            return lane_targets(self.config, lane, self.paths)
        own = self.config.paths_for(lane)
        return [
            name
            for name in self.change.files
            if name.endswith((".py", ".pyi")) and any(within(name, path) for path in own)
        ]

    def source_commands(self, lane: str) -> list[list[str]]:
        if self.change is None or lane not in _DIFF_FILE_LANES:
            if self.commands_cache is None:
                self.commands_cache = lane_commands(
                    self.config, paths=self.paths, no_fix=self.no_fix
                )
            return self.commands_cache[lane]
        targets = tuple(self.source_targets(lane))
        if not targets:
            return []
        return lane_commands(self.config, paths=targets, no_fix=self.no_fix)[lane]


def suppression_findings(
    config: Config, entries: list[RecordEntry], paths: tuple[str, ...] | None
) -> list[Finding]:
    """Scan the project, or only paths, and hold every suppression to the record.

    Configuration settings and stale entries are checked only on a full scan, since a subset
    cannot tell an entry that covers nothing from one covering a file outside the subset.
    """
    root = config.root
    files = project_files(root, config.scan_exclude)
    if paths is not None:
        files = scope_files(root, config.scan_exclude, paths)
    findings: list[Finding] = []
    sites: list[Site] = [] if paths is not None else config_sites(root)
    for name in files:
        found = _file_sites(root, name)
        if isinstance(found, Finding):
            findings.append(found)
        else:
            sites.extend(found)
    return findings + check_suppressions(
        sites, entries, full_scan=paths is None, record_path=config.record.path
    )


def _file_sites(root: Path, name: str) -> list[Site] | Finding:
    try:
        return comment_sites(name, (root / name).read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError) as error:
        return Finding(name, 0, UNSCANNED, f"cannot be scanned: {error}")


def run_pipeline(
    config: Config,
    *,
    requested: tuple[str, ...],
    paths: tuple[str, ...] | None,
    no_fix: bool,
    fail_fast: bool,
    out: TextIO,
    runner: Runner = run_subprocess,
    today: date,
    clock: Callable[[], float] = time.monotonic,
    change: Change | None = None,
    report: Path | None = None,
) -> int:
    """Run the selected lanes phase by phase and return the exit code: 0 pass, 1 fail.

    With change set the run is a diff run, narrowed to what changed; with report set, the
    outcome of every lane is also written there as JSON.
    """
    known = all_lanes(config)
    unknown = sorted(set(requested) - set(known))
    if unknown:
        msg = f"unknown tool {', '.join(unknown)}; known: {', '.join(known)}"
        raise UsageError(msg)
    if change is not None and paths is not None:
        msg = "-p and --diff each choose what to check; give one of them"
        raise UsageError(msg)
    state = _Run(config, paths, out, today, clock, clock(), runner, no_fix, change)
    if change is not None:
        _describe_change(change, out)
    failed = False
    for phase, lanes in lane_phases(config):
        selected = [lane for lane in lanes if _selected(lane, config, requested)]
        if phase == "runners" and selected and (failed or paths is not None):
            reason = (
                "a format or detector lane failed"
                if failed
                else "-p limits the run to format and detectors"
            )
            out.write(f"py-qa: runners not run: {reason}\n")
            state.results.extend(
                LaneResult(lane, phase, "not run" if lane in selected else "off") for lane in lanes
            )
            break
        for lane in lanes:
            if lane not in selected:
                state.results.append(LaneResult(lane, phase, "off"))
                continue
            out.write(f"== {lane} ==\n")
            out.flush()
            started = clock()
            status, note = _run_lane(state, lane)
            state.results.append(LaneResult(lane, phase, status, clock() - started, note))
            failed = failed or status == "FAIL"
            if failed and fail_fast:
                return _finish(state, failed=True, report=report)
    return _finish(state, failed=failed, report=report)


def _describe_change(change: Change, out: TextIO) -> None:
    count = len(change.files) + len(change.deleted)
    noun = "file" if count == 1 else "files"
    out.write(
        f"py-qa: diff run against {change.base} (merge base {change.merge_base[:12]}): "
        f"{count} changed {noun}\n"
    )
    out.writelines(f"  {name}\n" for name in change.files)
    out.writelines(f"  {name} (deleted)\n" for name in change.deleted)


def _selected(lane: str, config: Config, requested: tuple[str, ...]) -> bool:
    if requested:
        return lane in requested
    if lane not in config.tools:
        return True
    if lane == "summary" and config.summary_file is None:
        return False
    return config.tools[lane]


def _run_lane(state: _Run, lane: str) -> tuple[str, str]:
    """Run one lane and return its status, PASS, FAIL or skip, and a note for the report."""
    config = state.config
    if lane in BUILTIN_LANES:
        return ("PASS" if _report(state.builtin(lane), state.out) else "FAIL"), ""
    check = next((check for check in config.checks if check.name == lane), None)
    if check is not None:
        return _project_check(state, check)
    if lane == "test":
        return _test_lane(state)
    steps = state.source_commands(lane)
    if _external(state, lane, steps):
        return "PASS", ""
    if lane == "fmt" and state.no_fix:
        detail = format_diff_command(config, state.source_targets(lane))
        if detail is not None:
            state.step(detail)
    return "FAIL", ""


def _report(findings: list[Finding], out: TextIO) -> bool:
    out.writelines(finding.render() + "\n" for finding in sorted(findings))
    return not findings


def _external(state: _Run, lane: str, steps: list[list[str]]) -> bool:
    identifiers = _LANE_IDENTIFIERS.get(lane, ())
    if not steps:
        state.out.write(f"py-qa: {lane}: nothing to check within this lane's paths\n")
    for index, command in enumerate(steps):
        if state.step(command) == 0:
            continue
        if identifiers:
            identifier = identifiers[min(index, len(identifiers) - 1)]
            state.out.write(f"py-qa: {lane} failed: {identifier} (py-qa rule-doc {identifier})\n")
        return False
    return True


def expand(command: tuple[str, ...], tokens: dict[str, list[str]]) -> list[str]:
    """Return the command with each whole-argument placeholder replaced by its values."""
    expanded: list[str] = []
    for argument in command:
        expanded.extend(tokens.get(argument, [argument]))
    return expanded


def _project_check(state: _Run, check: ProjectCheck) -> tuple[str, str]:
    out = state.out
    tokens = {"{python}": [sys.executable]}
    command = check.command
    change = state.change
    if change is not None:
        if not check.in_diff:
            out.write(f"py-qa: {check.name}: runs in the full run only\n")
            return "skip", "full run only"
        watched = [
            name
            for name in (*change.files, *change.deleted)
            if check.paths is None or match_any(check.paths, name)
        ]
        if check.paths is not None and not watched:
            out.write(f"py-qa: {check.name}: no change to the files it checks\n")
            return "skip", "no change to the files it checks"
        if check.diff_command is not None:
            present = set(change.files)
            tokens["{files}"] = [name for name in watched if name in present]
            tokens["{base}"] = [change.base]
            command = check.diff_command
    if state.step(expand(command, tokens)) == 0:
        return "PASS", ""
    out.write(f"py-qa: {check.name} failed: {check.name} (py-qa rule-doc {check.name})\n")
    return "FAIL", ""


def _test_lane(state: _Run) -> tuple[str, str]:
    config = state.config
    out = state.out
    python = {"{python}": [sys.executable]}
    for setup in config.test_setup:
        if state.step(expand(setup, python)) != 0:
            out.write(
                f"py-qa: test setup failed: {' '.join(setup)}; pyqaci.tests "
                "(py-qa rule-doc pyqaci.tests)\n"
            )
            return "FAIL", "setup failed"
    full = [expand(tuple(step), python) for step in test_commands(config)]
    if state.change is None:
        return ("PASS" if _external(state, "test", full) else "FAIL"), ""
    selection = select_tests(config, state.change)
    state.selection = selection
    _describe_selection(selection, out)
    if selection.missing:
        out.write("py-qa: test failed: [[tool.py-qa.diff.map]] names tests that do not exist\n")
        return "FAIL", "the diff map names missing tests"
    if selection.full:
        return ("PASS" if _external(state, "test", full) else "FAIL"), "every test"
    if not selection.tests:
        out.write("py-qa: test: no test can be affected by the change\n")
        return "PASS", "no affected test"
    tokens = {**python, "{tests}": list(selection.tests), "{base}": [state.change.base]}
    if config.test_diff_command is not None:
        narrowed = [expand(config.test_diff_command, tokens)]
    elif config.test_command is not None:
        out.write(
            "py-qa: test: the project's test command takes no test list, so it runs whole; "
            "[tool.py-qa.test] diff_command narrows it\n"
        )
        narrowed = full
    else:
        narrowed = [[sys.executable, "-m", "pytest", *selection.tests]]
    ok = _external(state, "test", narrowed)
    return ("PASS" if ok else "FAIL"), f"{len(selection.tests)} affected test files"


def _describe_selection(selection: Selection, out: TextIO) -> None:
    out.writelines(f"py-qa: test: every test runs: {reason}\n" for reason in selection.full_reasons)
    out.writelines(
        f"py-qa: test: {name} is named by [[tool.py-qa.diff.map]] and does not exist\n"
        for name in selection.missing
    )
    out.writelines(
        f"py-qa: test: {name}: no test is known to read it\n" for name in selection.unmapped
    )
    out.writelines(
        f"py-qa: test: {name}: no test imports or names it\n" for name in selection.untested
    )
    if not selection.full:
        noun = "file" if len(selection.tests) == 1 else "files"
        out.write(f"py-qa: test: {len(selection.tests)} affected test {noun}\n")


def _finish(state: _Run, *, failed: bool, report: Path | None) -> int:
    out = state.out
    total = state.clock() - state.started
    out.write("\n")
    for result in state.results:
        took = "" if result.seconds is None else f" {result.seconds:>6.1f}s"
        out.write(f"{result.status:8} {result.name:12}{took}".rstrip() + "\n")
    out.write(f"{'':8} {'total':12} {total:>6.1f}s\n")
    if report is not None:
        _write_report(state, report, failed=failed, total=total)
    if failed:
        out.write(f"\nFAIL\n{METHOD_LINE}\n")
        return 1
    out.write("\nPASS\n")
    return 0


def _write_report(state: _Run, report: Path, *, failed: bool, total: float) -> None:
    change = state.change
    data: dict[str, object] = {
        "py_qa": __version__,
        "result": "FAIL" if failed else "PASS",
        "mode": "diff" if change is not None else "paths" if state.paths is not None else "full",
        "seconds": round(total, 3),
        "lanes": [
            {
                "name": result.name,
                "phase": result.phase,
                "status": result.status,
                "seconds": None if result.seconds is None else round(result.seconds, 3),
                "note": result.note,
            }
            for result in state.results
        ],
    }
    if state.paths is not None:
        data["paths"] = list(state.paths)
    if change is not None:
        data["diff"] = {
            "base": change.base,
            "merge_base": change.merge_base,
            "changed": list(change.files),
            "deleted": list(change.deleted),
        }
    if state.selection is not None:
        selection = state.selection
        data["tests"] = {
            "full": selection.full,
            "full_reasons": list(selection.full_reasons),
            "selected": list(selection.tests),
            "reached_by": {test: list(names) for test, names in selection.reached_by.items()},
            "unmapped": list(selection.unmapped),
            "untested": list(selection.untested),
            "missing": list(selection.missing),
        }
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
