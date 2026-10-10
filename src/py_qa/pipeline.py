"""The run: format, then every detector, then the runners, which run only if all before passed."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from py_qa.defences import Defence, active_defences
from py_qa.docs import check_docs
from py_qa.finding import Finding
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
)
from py_qa.tools import lane_commands

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date
    from pathlib import Path
    from typing import TextIO

    from py_qa.config import Config

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
# Lanes whose tool prints no identifier of its own: py-qa prints one for each failing step.
_LANE_IDENTIFIERS = {
    "fmt": ("pyqaci.format",),
    "test": ("pyqaci.tests", "pyqaci.coverage"),
    "audit": ("pyqaci.audit",),
}


class UsageError(Exception):
    """The command line asks for something py-qa does not have."""


def run_subprocess(command: list[str], cwd: Path) -> int:
    """Run one tool with its output going straight to the terminal, and return its exit code."""
    return subprocess.run(command, cwd=cwd, check=False).returncode


@dataclass
class _Run:
    config: Config
    paths: tuple[str, ...] | None
    out: TextIO
    today: date
    entries_cache: tuple[list[RecordEntry], list[Finding]] | None = None
    defences_cache: list[Defence] | None = None
    results: list[tuple[str, str]] = field(default_factory=list)

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
    return findings + check_suppressions(sites, entries, full_scan=paths is None)


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
) -> int:
    """Run the selected lanes phase by phase and return the exit code: 0 pass, 1 fail."""
    unknown = sorted(set(requested) - set(LANES))
    if unknown:
        msg = f"unknown tool {', '.join(unknown)}; known: {', '.join(LANES)}"
        raise UsageError(msg)
    state = _Run(config, paths, out, today)
    commands = lane_commands(config, paths=paths, no_fix=no_fix)
    failed = False
    for phase, lanes in PHASES:
        selected = [lane for lane in lanes if _selected(lane, config, requested)]
        if phase == "runners" and selected and (failed or paths is not None):
            reason = (
                "a format or detector lane failed"
                if failed
                else "-p limits the run to format and detectors"
            )
            out.write(f"py-qa: runners not run: {reason}\n")
            state.results.extend((lane, "not run" if lane in selected else "off") for lane in lanes)
            break
        for lane in lanes:
            if lane not in selected:
                state.results.append((lane, "off"))
                continue
            out.write(f"== {lane} ==\n")
            out.flush()
            if lane in BUILTIN_LANES:
                ok = _report(state.builtin(lane), out)
            else:
                ok = _external(lane, commands[lane], config, runner, out)
            state.results.append((lane, "PASS" if ok else "FAIL"))
            failed = failed or not ok
            if failed and fail_fast:
                return _finish(state, failed=True)
    return _finish(state, failed=failed)


def _selected(lane: str, config: Config, requested: tuple[str, ...]) -> bool:
    if requested:
        return lane in requested
    if lane == "summary" and config.summary_file is None:
        return False
    return config.tools[lane]


def _report(findings: list[Finding], out: TextIO) -> bool:
    out.writelines(finding.render() + "\n" for finding in sorted(findings))
    return not findings


def _external(
    lane: str, steps: list[list[str]], config: Config, runner: Runner, out: TextIO
) -> bool:
    identifiers = _LANE_IDENTIFIERS.get(lane, ())
    for index, command in enumerate(steps):
        out.flush()
        if runner(command, config.root) == 0:
            continue
        if identifiers:
            identifier = identifiers[min(index, len(identifiers) - 1)]
            out.write(f"py-qa: {lane} failed: {identifier} (py-qa rule-doc {identifier})\n")
        return False
    return True


def _finish(state: _Run, *, failed: bool) -> int:
    out = state.out
    out.write("\n")
    for lane, status in state.results:
        out.write(f"{status:8} {lane}\n")
    if failed:
        out.write(f"\nFAIL\n{METHOD_LINE}\n")
        return 1
    out.write("\nPASS\n")
    return 0
