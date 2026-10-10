"""The [tool.py-qa] table of pyproject.toml: every key, its default, and its validation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomllib

TOOLS = (
    "fmt",
    "record",
    "suppression",
    "summary",
    "docs",
    "ruff",
    "mypy",
    "pylint",
    "test",
    "coverage",
    "audit",
)
OFF_BY_DEFAULT = frozenset({"audit"})
# Ruff's formatter by default; Black for a project already formatted by it, which must then
# install Black itself, since py-qa does not depend on it.
FORMATTERS = ("ruff", "black")
# The table's name before py-qa-ci 0.2.0, when the tool was called python-qa-ci.
FORMER_TABLE = "python-qa"

_TOP_KEYS = frozenset(
    {
        "record",
        "docs_dir",
        "paths",
        "scan_exclude",
        "pylint_plugins",
        "pylint_enable",
        "tools",
        "coverage",
        "summary",
        "sensitive_repr",
        "formatter",
        "test",
        "lane_paths",
        "check",
        "diff",
        "lock",
        "rule_doc_command",
    }
)
# Lanes that read source and can be given paths of their own in [tool.py-qa.lane_paths].
PATH_LANES = ("fmt", "ruff", "mypy", "pylint")
_RECORD_KEYS = frozenset({"path", "max_total", "max_per_rule", "max_review_days"})
# A project check runs among the detectors, or after the test lane among the runners.
CHECK_PHASES = ("detectors", "runners")
_CHECK_KEYS = frozenset(
    {"name", "command", "description", "doc", "phase", "paths", "diff_command", "diff", "verdict"}
)
_CHECK_NAME = re.compile(r"[a-z][a-z0-9_-]*\Z")
# The placeholders a command may hold as a whole argument, and where each one is allowed.
_TOKENS = {
    "check command": {"{python}"},
    "check diff_command": {"{python}", "{files}", "{base}", "{merge_base}", "{range}"},
    "test command": {"{python}"},
    "test diff_command": {"{python}", "{tests}", "{base}", "{merge_base}", "{range}"},
    "diff selector": {"{python}", "{base}", "{merge_base}", "{range}"},
    "test setup": {"{python}"},
    "rule_doc_command": {"{python}", "{identifier}"},
}
UNMAPPED_POLICIES = ("full", "ignore")
# A change to one of these can change any test's outcome, so in a diff run it runs them all.
DEFAULT_FULL_TESTS_ON = (
    "pyproject.toml",
    "uv.lock",
    "poetry.lock",
    "pdm.lock",
    "setup.py",
    "setup.cfg",
    "tox.ini",
    "pytest.ini",
    "requirements*.txt",
    ".python-version",
)


class ConfigError(Exception):
    """The configuration cannot be used; the message names the key."""


# A JSON report a command writes, and the dotted key in it that must be true for a pass.
Verdict = tuple[str, tuple[str, ...]]


@dataclass(frozen=True)
class RecordPolicy:
    """Where the project record lives and the limits that keep it small."""

    path: str = "qa/record.toml"
    max_total: int = 20
    max_per_rule: int = 5
    max_review_days: int = 180


@dataclass(frozen=True)
class ProjectCheck:
    """A check the project supplies: a command run as a lane of its own."""

    name: str
    command: tuple[str, ...]
    description: str
    doc: str
    phase: str = "detectors"
    paths: tuple[str, ...] | None = None
    diff_command: tuple[str, ...] | None = None
    in_diff: bool = True
    verdict: Verdict | None = None


@dataclass(frozen=True)
class DiffMapEntry:
    """Tests that cover files the import graph cannot reach, such as data a test reads."""

    glob: str
    tests: tuple[str, ...]
    why: str = ""
    exclude: tuple[str, ...] = ()


@dataclass(frozen=True)
class DiffSelector:
    """A project command that names more tests for a change, as JSON, beside py-qa's graph."""

    command: tuple[str, ...]
    tests_key: str
    unmapped_key: str | None = None


@dataclass(frozen=True)
class DiffPolicy:
    """How a diff run (`py-qa run --diff`) finds what changed and what it must test."""

    base: str | None = None
    full_tests_on: tuple[str, ...] = DEFAULT_FULL_TESTS_ON
    unmapped: str = "full"
    map: tuple[DiffMapEntry, ...] = ()
    selector: DiffSelector | None = None


@dataclass(frozen=True)
class Config:
    """The resolved configuration for one project root."""

    root: Path
    record: RecordPolicy
    docs_dir: str
    paths: tuple[str, ...]
    scan_exclude: tuple[str, ...]
    pylint_plugins: tuple[str, ...]
    pylint_enable: tuple[str, ...]
    tools: dict[str, bool]
    coverage_fail_under: float
    summary_file: str | None
    formatter: str
    sensitive_names: tuple[str, ...] | None
    redacting_types: tuple[str, ...] | None
    test_command: tuple[str, ...] | None = None
    lane_paths: dict[str, tuple[str, ...]] = field(default_factory=dict)
    checks: tuple[ProjectCheck, ...] = ()
    diff: DiffPolicy = field(default_factory=DiffPolicy)
    test_diff_command: tuple[str, ...] | None = None
    test_setup: tuple[tuple[str, ...], ...] = ()
    test_verdict: Verdict | None = None
    test_diff_verdict: Verdict | None = None
    lock: bool = True
    lock_path: str | None = None
    rule_doc_command: tuple[str, ...] | None = None

    def paths_for(self, lane: str) -> tuple[str, ...]:
        """Return the paths a lane reads: its own from lane_paths, or paths."""
        return self.lane_paths.get(lane, self.paths)

    @property
    def record_path(self) -> Path:
        """Return the absolute path of the project record."""
        return self.root / self.record.path


def read_pyproject(root: Path) -> dict[str, Any]:
    """Return the parsed pyproject.toml at root, or an empty table when there is none."""
    path = root / "pyproject.toml"
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        msg = f"pyproject.toml: cannot parse: {error}"
        raise ConfigError(msg) from error


def load_config(root: Path) -> Config:
    """Read [tool.py-qa] from root's pyproject.toml, rejecting unknown keys and bad types."""
    tool = read_pyproject(root).get("tool", {})
    if FORMER_TABLE in tool:
        # Ignoring it would run every lane on the defaults, silently dropping the project's own
        # record path, plugins and switches.
        msg = f"[tool.{FORMER_TABLE}] is the former name of this table; it is renamed [tool.py-qa]"
        raise ConfigError(msg)
    table = _table(tool.get("py-qa", {}), "[tool.py-qa]")
    unknown = sorted(set(table) - _TOP_KEYS)
    if unknown:
        msg = f"[tool.py-qa]: unknown key {', '.join(unknown)}"
        raise ConfigError(msg)
    paths = _strings(table, "paths", "[tool.py-qa]")
    if paths is None:
        paths = tuple(name for name in ("src", "tests") if (root / name).is_dir()) or (".",)
    summary = _table(table.get("summary", {}), "[tool.py-qa.summary]")
    sensitive = _table(table.get("sensitive_repr", {}), "[tool.py-qa.sensitive_repr]")
    _reject_unknown(summary, {"file"}, "[tool.py-qa.summary]")
    _reject_unknown(sensitive, {"names", "redacting_types"}, "[tool.py-qa.sensitive_repr]")
    test = _table(table.get("test", {}), "[tool.py-qa.test]")
    _reject_unknown(
        test, {"command", "diff_command", "setup", "verdict", "diff_verdict"}, "[tool.py-qa.test]"
    )
    lock = table.get("lock", True)
    if not isinstance(lock, bool | str) or lock == "":
        msg = "[tool.py-qa]: lock must be true, false or a path"
        raise ConfigError(msg)
    return Config(
        root=root,
        record=_record_policy(table),
        docs_dir=_string(table, "docs_dir", "[tool.py-qa]") or "docs/defences",
        paths=paths,
        scan_exclude=_strings(table, "scan_exclude", "[tool.py-qa]") or (),
        pylint_plugins=_strings(table, "pylint_plugins", "[tool.py-qa]") or (),
        pylint_enable=_strings(table, "pylint_enable", "[tool.py-qa]") or (),
        tools=_tools(table),
        coverage_fail_under=_coverage(table),
        summary_file=_string(summary, "file", "[tool.py-qa.summary]"),
        formatter=_formatter(table),
        sensitive_names=_strings(sensitive, "names", "[tool.py-qa.sensitive_repr]"),
        redacting_types=_strings(sensitive, "redacting_types", "[tool.py-qa.sensitive_repr]"),
        test_command=_command(test, "command", "[tool.py-qa.test]", "test command"),
        lane_paths=_lane_paths(table),
        checks=_checks(table),
        diff=_diff_policy(table),
        test_diff_command=_command(
            test, "diff_command", "[tool.py-qa.test]", "test diff_command", required="{tests}"
        ),
        test_setup=_setup(test),
        test_verdict=_verdict(test, "[tool.py-qa.test]"),
        test_diff_verdict=_verdict(test, "[tool.py-qa.test]", "diff_verdict"),
        lock=lock is not False,
        lock_path=lock if isinstance(lock, str) else None,
        rule_doc_command=_command(
            table, "rule_doc_command", "[tool.py-qa]", "rule_doc_command", required="{identifier}"
        ),
    )


def _command(
    table: dict[str, Any], key: str, where: str, kind: str, *, required: str | None = None
) -> tuple[str, ...] | None:
    """Return an argv list from table[key], run without a shell, or None when it is absent."""
    command = table.get(key)
    if command is None:
        return None
    return _argv(command, key, where, kind, required)


def _argv(
    command: object, key: str, where: str, kind: str, required: str | None
) -> tuple[str, ...]:
    if not isinstance(command, list) or not command or not all(isinstance(a, str) for a in command):
        msg = f"{where}: {key} must be a non-empty list of strings, run without a shell"
        raise ConfigError(msg)
    allowed = _TOKENS[kind]
    for argument in command:
        for token in re.findall(r"\{[a-z_]+\}", argument):
            if token not in allowed or argument != token:
                msg = (
                    f"{where}: {key}: {token} is not a placeholder here; a placeholder is a whole "
                    f"argument, one of {', '.join(sorted(allowed))}"
                )
                raise ConfigError(msg)
    if required is not None and required not in command:
        msg = f"{where}: {key} must hold {required} as an argument"
        raise ConfigError(msg)
    return tuple(command)


def _setup(test: dict[str, Any]) -> tuple[tuple[str, ...], ...]:
    setup = test.get("setup", [])
    if not isinstance(setup, list) or not all(isinstance(step, list) for step in setup):
        msg = "[tool.py-qa.test]: setup must be a list of commands, each a list of strings"
        raise ConfigError(msg)
    return tuple(_argv(step, "setup", "[tool.py-qa.test]", "test setup", None) for step in setup)


def _checks(table: dict[str, Any]) -> tuple[ProjectCheck, ...]:
    raw = table.get("check", [])
    if not isinstance(raw, list) or not all(isinstance(entry, dict) for entry in raw):
        msg = "[tool.py-qa]: check must be an array of tables, [[tool.py-qa.check]]"
        raise ConfigError(msg)
    checks: list[ProjectCheck] = []
    for number, entry in enumerate(raw, start=1):
        where = f"[[tool.py-qa.check]] #{number}"
        _reject_unknown(entry, _CHECK_KEYS, where)
        name = _string(entry, "name", where)
        if name is None or not _CHECK_NAME.match(name):
            msg = f"{where}: name must be lower case letters, digits, '-' and '_', from a letter"
            raise ConfigError(msg)
        if name in TOOLS:
            msg = f"{where}: {name} is the name of a py-qa lane"
            raise ConfigError(msg)
        if any(check.name == name for check in checks):
            msg = f"{where}: the check {name} is declared twice"
            raise ConfigError(msg)
        command = _argv(entry.get("command"), "command", where, "check command", None)
        description = _string(entry, "description", where)
        if not description:
            msg = f"{where}: description, the standing instruction the check enforces, is required"
            raise ConfigError(msg)
        doc = _string(entry, "doc", where)
        if not doc:
            msg = f"{where}: doc, the file that documents the check, is required"
            raise ConfigError(msg)
        phase = _string(entry, "phase", where) or "detectors"
        if phase not in CHECK_PHASES:
            msg = f"{where}: phase must be one of {', '.join(CHECK_PHASES)}"
            raise ConfigError(msg)
        in_diff = entry.get("diff", True)
        if not isinstance(in_diff, bool):
            msg = f"{where}: diff must be true or false"
            raise ConfigError(msg)
        paths = _strings(entry, "paths", where)
        if paths is not None and not paths:
            msg = f"{where}: paths must be a non-empty list of globs, or left out to always run"
            raise ConfigError(msg)
        checks.append(
            ProjectCheck(
                name=name,
                command=command,
                description=description,
                doc=doc,
                phase=phase,
                paths=paths,
                diff_command=_command(entry, "diff_command", where, "check diff_command"),
                in_diff=in_diff,
                verdict=_verdict(entry, where),
            )
        )
    return tuple(checks)


def _verdict(entry: dict[str, Any], where: str, name: str = "verdict") -> Verdict | None:
    raw = entry.get(name)
    if raw is None:
        return None
    if not isinstance(raw, dict):
        msg = f"{where}: {name} must be a table: {{ file = <path>, key = <dotted key> }}"
        raise ConfigError(msg)
    _reject_unknown(raw, {"file", "key"}, f"{where} {name}")
    file, key = raw.get("file"), raw.get("key")
    if not isinstance(file, str) or not file or not isinstance(key, str) or not key.strip("."):
        msg = f"{where}: {name} must name a file and a dotted key, both non-empty strings"
        raise ConfigError(msg)
    return file, tuple(part for part in key.split(".") if part)


def _selector(diff: dict[str, Any]) -> DiffSelector | None:
    where = "[tool.py-qa.diff.selector]"
    raw = diff.get("selector")
    if raw is None:
        return None
    selector = _table(raw, where)
    _reject_unknown(selector, {"command", "tests_key", "unmapped_key"}, where)
    command = _argv(selector.get("command"), "command", where, "diff selector", None)
    tests_key = _string(selector, "tests_key", where)
    if not tests_key:
        msg = f"{where}: tests_key, the JSON key listing the tests it selects, is required"
        raise ConfigError(msg)
    return DiffSelector(command, tests_key, _string(selector, "unmapped_key", where))


def _diff_policy(table: dict[str, Any]) -> DiffPolicy:
    where = "[tool.py-qa.diff]"
    diff = _table(table.get("diff", {}), where)
    _reject_unknown(diff, {"base", "full_tests_on", "unmapped", "map", "selector"}, where)
    unmapped = _string(diff, "unmapped", where) or "full"
    if unmapped not in UNMAPPED_POLICIES:
        msg = f"{where}: unmapped must be one of {', '.join(UNMAPPED_POLICIES)}"
        raise ConfigError(msg)
    raw = diff.get("map", [])
    if not isinstance(raw, list) or not all(isinstance(entry, dict) for entry in raw):
        msg = f"{where}: map must be an array of tables, [[tool.py-qa.diff.map]]"
        raise ConfigError(msg)
    entries: list[DiffMapEntry] = []
    for number, entry in enumerate(raw, start=1):
        at = f"[[tool.py-qa.diff.map]] #{number}"
        _reject_unknown(entry, {"glob", "tests", "why", "exclude"}, at)
        glob = _string(entry, "glob", at)
        if not glob:
            msg = f"{at}: glob is required"
            raise ConfigError(msg)
        tests = _strings(entry, "tests", at)
        if tests is None:
            msg = f"{at}: tests is required: the tests that cover the files, or [] for none"
            raise ConfigError(msg)
        exclude = _strings(entry, "exclude", at) or ()
        entries.append(DiffMapEntry(glob, tests, _string(entry, "why", at) or "", exclude))
    full = _strings(diff, "full_tests_on", where)
    return DiffPolicy(
        base=_string(diff, "base", where),
        full_tests_on=DEFAULT_FULL_TESTS_ON if full is None else full,
        unmapped=unmapped,
        map=tuple(entries),
        selector=_selector(diff),
    )


def _lane_paths(table: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    where = "[tool.py-qa.lane_paths]"
    lanes = _table(table.get("lane_paths", {}), where)
    unknown = sorted(set(lanes) - set(PATH_LANES))
    if unknown:
        msg = f"{where}: unknown lane {', '.join(unknown)}; known: {', '.join(PATH_LANES)}"
        raise ConfigError(msg)
    resolved: dict[str, tuple[str, ...]] = {}
    for lane in lanes:
        paths = _strings(lanes, lane, where)
        if not paths:
            msg = f"{where}: {lane} must be a non-empty list of strings"
            raise ConfigError(msg)
        resolved[lane] = paths
    return resolved


def _record_policy(table: dict[str, Any]) -> RecordPolicy:
    raw = table.get("record")
    if raw is None:
        return RecordPolicy()
    if isinstance(raw, str):
        return RecordPolicy(path=raw)
    record = _table(raw, "[tool.py-qa.record]")
    _reject_unknown(record, _RECORD_KEYS, "[tool.py-qa.record]")
    defaults = RecordPolicy()
    return RecordPolicy(
        path=_string(record, "path", "[tool.py-qa.record]") or defaults.path,
        max_total=_count(record, "max_total", defaults.max_total),
        max_per_rule=_count(record, "max_per_rule", defaults.max_per_rule),
        max_review_days=_count(record, "max_review_days", defaults.max_review_days),
    )


def _tools(table: dict[str, Any]) -> dict[str, bool]:
    switches = _table(table.get("tools", {}), "[tool.py-qa.tools]")
    tools = {name: name not in OFF_BY_DEFAULT for name in TOOLS}
    for name, value in switches.items():
        if name not in tools:
            msg = f"[tool.py-qa.tools]: unknown tool {name}; known: {', '.join(TOOLS)}"
            raise ConfigError(msg)
        if not isinstance(value, bool):
            msg = f"[tool.py-qa.tools]: {name} must be true or false"
            raise ConfigError(msg)
        tools[name] = value
    return tools


def _formatter(table: dict[str, Any]) -> str:
    formatter = _string(table, "formatter", "[tool.py-qa]") or "ruff"
    if formatter not in FORMATTERS:
        msg = f"[tool.py-qa]: formatter must be one of {', '.join(FORMATTERS)}"
        raise ConfigError(msg)
    return formatter


def _coverage(table: dict[str, Any]) -> float:
    coverage = _table(table.get("coverage", {}), "[tool.py-qa.coverage]")
    _reject_unknown(coverage, {"fail_under"}, "[tool.py-qa.coverage]")
    value = coverage.get("fail_under", 80)
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = "[tool.py-qa.coverage]: fail_under must be a number"
        raise ConfigError(msg)
    return float(value)


def _table(value: object, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        msg = f"{where} must be a table"
        raise ConfigError(msg)
    return value


def _reject_unknown(table: dict[str, Any], known: set[str] | frozenset[str], where: str) -> None:
    unknown = sorted(set(table) - set(known))
    if unknown:
        msg = f"{where}: unknown key {', '.join(unknown)}"
        raise ConfigError(msg)


def _string(table: dict[str, Any], key: str, where: str) -> str | None:
    value = table.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        msg = f"{where}: {key} must be a string"
        raise ConfigError(msg)
    return value


def _strings(table: dict[str, Any], key: str, where: str) -> tuple[str, ...] | None:
    value = table.get(key)
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        msg = f"{where}: {key} must be a list of strings"
        raise ConfigError(msg)
    return tuple(value)


def _count(table: dict[str, Any], key: str, default: int) -> int:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        msg = f"[tool.py-qa.record]: {key} must be a non-negative integer"
        raise ConfigError(msg)
    return value
