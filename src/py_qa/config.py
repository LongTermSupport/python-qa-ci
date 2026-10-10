"""The [tool.py-qa] table of pyproject.toml: every key, its default, and its validation."""

from __future__ import annotations

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
    }
)
# Lanes that read source and can be given paths of their own in [tool.py-qa.lane_paths].
PATH_LANES = ("fmt", "ruff", "mypy", "pylint")
_RECORD_KEYS = frozenset({"path", "max_total", "max_per_rule", "max_review_days"})


class ConfigError(Exception):
    """The configuration cannot be used; the message names the key."""


@dataclass(frozen=True)
class RecordPolicy:
    """Where the project record lives and the limits that keep it small."""

    path: str = "qa/record.toml"
    max_total: int = 20
    max_per_rule: int = 5
    max_review_days: int = 180


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
        test_command=_test_command(table),
        lane_paths=_lane_paths(table),
    )


def _test_command(table: dict[str, Any]) -> tuple[str, ...] | None:
    test = _table(table.get("test", {}), "[tool.py-qa.test]")
    _reject_unknown(test, {"command"}, "[tool.py-qa.test]")
    command = test.get("command")
    if command is None:
        return None
    if not isinstance(command, list) or not command or not all(isinstance(a, str) for a in command):
        msg = "[tool.py-qa.test]: command must be a non-empty list of strings, run without a shell"
        raise ConfigError(msg)
    return tuple(command)


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
