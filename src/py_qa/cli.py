"""The py-qa command: run the pipeline, list defences, resolve identifiers, keep the record."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from py_qa import __version__
from py_qa.config import ConfigError, load_config
from py_qa.defences import BUILTIN, active_defences
from py_qa.docs import check_docs, resolve
from py_qa.pipeline import LANES, METHOD_LINE, UsageError, run_pipeline, suppression_findings
from py_qa.record import RecordEntry, check_record, load_record
from py_qa.summary import check_summary, write_summary
from py_qa.tools import lane_commands, pylint_commands, pylint_messages

if TYPE_CHECKING:
    from py_qa.config import Config
    from py_qa.finding import Finding

_HARNESS_BUILTINS = frozenset(
    {
        "pyqaci.suppression.unrecorded",
        "pyqaci.suppression.blanket",
        "pyqaci.suppression.unscanned",
    }
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="py-qa",
        description="One QA entry point for Python projects, built for Defence Before Fix.",
        epilog=METHOD_LINE,
    )
    parser.add_argument("--version", action="version", version=f"py-qa {__version__}")
    commands = parser.add_subparsers(dest="command")

    run = commands.add_parser("run", help="format, every detector, then the runners")
    run.add_argument("-t", "--tool", action="append", default=[], choices=LANES, dest="tools")
    run.add_argument("-p", "--path", action="append", dest="paths")
    run.add_argument("--ci", action="store_true", help="check instead of fixing")
    run.add_argument("--no-fix", action="store_true", help="check instead of fixing")
    run.add_argument("--fail-fast", action="store_true", help="stop at the first failing lane")

    rules = commands.add_parser("rules", help="every active defence and the project record")
    rules.add_argument("--json", action="store_true")

    rule_doc = commands.add_parser("rule-doc", help="documentation for a printed identifier")
    rule_doc.add_argument("identifier")

    rule = commands.add_parser("rule", help="run one rule, on its own, on the paths given")
    rule.add_argument("identifier")
    rule.add_argument("paths", nargs="+")

    commands.add_parser("docs-check", help="fail if a listed identifier has no documentation")

    record = commands.add_parser("record", help="validate or list the project record")
    record.add_argument("action", choices=("check", "list"))

    summary = commands.add_parser("summary", help="write (or check) the agent summary region")
    summary.add_argument("--check", action="store_true")

    commands.add_parser("tools", help="every lane, whether it is on, and its tool")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run py-qa with argv and return its exit code: 0 pass, 1 findings, 2 usage error."""
    args = _parser().parse_args(argv)
    try:
        config = load_config(Path.cwd())
        return _dispatch(args, config)
    except (ConfigError, UsageError, ValueError) as error:
        sys.stderr.write(f"py-qa: error: {error}\n")
        return 2


def _today() -> date:
    return datetime.now(tz=UTC).date()


def _dispatch(args: argparse.Namespace, config: Config) -> int:
    command = args.command or "run"
    if command == "run":
        tools = getattr(args, "tools", [])
        paths = getattr(args, "paths", None)
        flags = (getattr(args, "no_fix", False), getattr(args, "ci", False))
        return run_pipeline(
            config,
            requested=tuple(tools),
            paths=tuple(paths) if paths else None,
            no_fix=any(flags) or bool(os.environ.get("CI")),
            fail_fast=bool(getattr(args, "fail_fast", False)),
            out=sys.stdout,
            today=_today(),
        )
    if command == "rules":
        return _rules(config, as_json=args.json)
    if command == "rule-doc":
        return _rule_doc(config, args.identifier)
    if command == "rule":
        return _rule(config, args.identifier, tuple(args.paths))
    if command == "docs-check":
        return _report(check_docs(config, active_defences(config)))
    if command == "record":
        return _record(config, args.action)
    if command == "summary":
        return _summary(config, check=args.check)
    return _tools(config)


def _entries(config: Config) -> tuple[list[RecordEntry], list[Finding]]:
    return load_record(
        config.record_path,
        config.record.path,
        today=_today(),
        max_review_days=config.record.max_review_days,
    )


def _report(findings: list[Finding]) -> int:
    for finding in sorted(findings):
        sys.stdout.write(finding.render() + "\n")
    return 1 if findings else 0


def _rules(config: Config, *, as_json: bool) -> int:
    defences = active_defences(config)
    entries, _ = _entries(config)
    if as_json:
        data = {
            "defences": [asdict(defence) | {"doc": defence.doc} for defence in defences],
            "record": [
                asdict(entry)
                | {"decided_on": entry.decided_on.isoformat()}
                | {"review_by": entry.review_by.isoformat()}
                for entry in entries
            ],
            "scan_exclude": list(config.scan_exclude),
        }
        sys.stdout.write(json.dumps(data, indent=2) + "\n")
        return 0
    width = max((len(defence.identifier) for defence in defences), default=0)
    for defence in defences:
        sys.stdout.write(
            f"{defence.identifier:{width}}  {defence.tool:9} {defence.origin:8} "
            f"{defence.summary}  ->  {defence.doc}\n"
        )
    noun = "exception" if len(entries) == 1 else "exceptions"
    sys.stdout.write(f"\nProject record ({config.record.path}): {len(entries)} {noun}\n")
    sys.stdout.writelines(_entry_line(entry) for entry in entries)
    if config.scan_exclude:
        sys.stdout.write("\nExcluded from the suppression scan and the bundled Pylint pass:\n")
        sys.stdout.writelines(f"  {pattern}\n" for pattern in config.scan_exclude)
    return 0


def _entry_line(entry: RecordEntry) -> str:
    return (
        f"  #{entry.number} {entry.rule}  {entry.path}  decided by {entry.decided_by} on "
        f"{entry.decided_on.isoformat()}, review by {entry.review_by.isoformat()}\n"
        f"      {entry.justification}\n"
    )


def _rule_doc(config: Config, identifier: str) -> int:
    text = resolve(identifier, config)
    if text is None:
        sys.stderr.write(f"py-qa: no documentation for {identifier}\n")
        return 1
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return 0


def _rule(config: Config, identifier: str, paths: tuple[str, ...]) -> int:
    """Run one rule alone on paths: exit 0 it did not fire, 1 it fired, 2 it could not run."""
    if identifier in _HARNESS_BUILTINS:
        entries, _ = _entries(config)
        findings = suppression_findings(config, entries, paths)
        return _report([finding for finding in findings if finding.rule == identifier])
    if identifier in BUILTIN:
        msg = f"{identifier}: run its lane with `py-qa run -t <lane>`; it reads no source"
        raise UsageError(msg)
    name = identifier.split("::", 1)[-1]
    messages = pylint_messages(config)
    symbols = {m.symbol: m.symbol for m in messages} | {m.msgid: m.symbol for m in messages}
    if name in symbols:
        commands = pylint_commands(config, paths, symbols[name])
        if not commands:
            msg = f"no Python file under {', '.join(paths)}"
            raise UsageError(msg)
        code = subprocess.run(commands[0], cwd=config.root, check=False).returncode
        fatal_or_usage = 1 | 32
        return 0 if code == 0 else 2 if code & fatal_or_usage else 1
    if re.fullmatch(r"[A-Z]+[0-9]+", name) and resolve(name, config) is not None:
        ruff = lane_commands(config, paths=paths, no_fix=True)["ruff"][0]
        command = [*ruff[:6], f"--select={name}", *ruff[6:]]
        return subprocess.run(command, cwd=config.root, check=False).returncode
    msg = (
        f"{identifier}: py-qa cannot run one rule alone for this identifier; the harness "
        "covers Pylint messages, Ruff codes and py-qa's suppression rules"
    )
    raise UsageError(msg)


def _record(config: Config, action: str) -> int:
    entries, invalid = _entries(config)
    if action == "list":
        noun = "exception" if len(entries) == 1 else "exceptions"
        sys.stdout.write(
            f"{config.record.path}: {len(entries)} {noun} (max_total {config.record.max_total}, "
            f"max_per_rule {config.record.max_per_rule})\n"
        )
        sys.stdout.writelines(_entry_line(entry) for entry in entries)
        return _report(invalid)
    policy = check_record(entries, config.record, config.record.path, _today())
    return _report(invalid + policy)


def _summary(config: Config, *, check: bool) -> int:
    if config.summary_file is None:
        sys.stderr.write("py-qa: no [tool.py-qa.summary] file is configured\n")
        return 2
    defences = active_defences(config)
    entries, _ = _entries(config)
    if check:
        return _report(check_summary(config, defences, entries))
    write_summary(config, defences, entries)
    sys.stdout.write(f"py-qa: wrote the summary region in {config.summary_file}\n")
    return 0


def _tools(config: Config) -> int:
    commands = lane_commands(config, paths=None, no_fix=True)
    for lane in LANES:
        state = "on" if config.tools[lane] else "off"
        if lane == "summary" and config.summary_file is None:
            state = "off (no summary file)"
        what = " ".join(commands[lane][0][2:4]) if commands.get(lane) else "py-qa"
        sys.stdout.write(f"{lane:12} {state:22} {what}\n")
    return 0
