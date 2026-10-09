"""The [tool.python-qa] table of pyproject.toml: every key, its default, and its validation."""

from __future__ import annotations

from dataclasses import dataclass
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
    }
)
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
    sensitive_names: tuple[str, ...] | None
    redacting_types: tuple[str, ...] | None

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
    """Read [tool.python-qa] from root's pyproject.toml, rejecting unknown keys and bad types."""
    table = _table(read_pyproject(root).get("tool", {}).get("python-qa", {}), "[tool.python-qa]")
    unknown = sorted(set(table) - _TOP_KEYS)
    if unknown:
        msg = f"[tool.python-qa]: unknown key {', '.join(unknown)}"
        raise ConfigError(msg)
    paths = _strings(table, "paths", "[tool.python-qa]")
    if paths is None:
        paths = tuple(name for name in ("src", "tests") if (root / name).is_dir()) or (".",)
    summary = _table(table.get("summary", {}), "[tool.python-qa.summary]")
    sensitive = _table(table.get("sensitive_repr", {}), "[tool.python-qa.sensitive_repr]")
    _reject_unknown(summary, {"file"}, "[tool.python-qa.summary]")
    _reject_unknown(sensitive, {"names", "redacting_types"}, "[tool.python-qa.sensitive_repr]")
    return Config(
        root=root,
        record=_record_policy(table),
        docs_dir=_string(table, "docs_dir", "[tool.python-qa]") or "docs/defences",
        paths=paths,
        scan_exclude=_strings(table, "scan_exclude", "[tool.python-qa]") or (),
        pylint_plugins=_strings(table, "pylint_plugins", "[tool.python-qa]") or (),
        pylint_enable=_strings(table, "pylint_enable", "[tool.python-qa]") or (),
        tools=_tools(table),
        coverage_fail_under=_coverage(table),
        summary_file=_string(summary, "file", "[tool.python-qa.summary]"),
        sensitive_names=_strings(sensitive, "names", "[tool.python-qa.sensitive_repr]"),
        redacting_types=_strings(sensitive, "redacting_types", "[tool.python-qa.sensitive_repr]"),
    )


def _record_policy(table: dict[str, Any]) -> RecordPolicy:
    raw = table.get("record")
    if raw is None:
        return RecordPolicy()
    if isinstance(raw, str):
        return RecordPolicy(path=raw)
    record = _table(raw, "[tool.python-qa.record]")
    _reject_unknown(record, _RECORD_KEYS, "[tool.python-qa.record]")
    defaults = RecordPolicy()
    return RecordPolicy(
        path=_string(record, "path", "[tool.python-qa.record]") or defaults.path,
        max_total=_count(record, "max_total", defaults.max_total),
        max_per_rule=_count(record, "max_per_rule", defaults.max_per_rule),
        max_review_days=_count(record, "max_review_days", defaults.max_review_days),
    )


def _tools(table: dict[str, Any]) -> dict[str, bool]:
    switches = _table(table.get("tools", {}), "[tool.python-qa.tools]")
    tools = {name: name not in OFF_BY_DEFAULT for name in TOOLS}
    for name, value in switches.items():
        if name not in tools:
            msg = f"[tool.python-qa.tools]: unknown tool {name}; known: {', '.join(TOOLS)}"
            raise ConfigError(msg)
        if not isinstance(value, bool):
            msg = f"[tool.python-qa.tools]: {name} must be true or false"
            raise ConfigError(msg)
        tools[name] = value
    return tools


def _coverage(table: dict[str, Any]) -> float:
    coverage = _table(table.get("coverage", {}), "[tool.python-qa.coverage]")
    _reject_unknown(coverage, {"fail_under"}, "[tool.python-qa.coverage]")
    value = coverage.get("fail_under", 80)
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = "[tool.python-qa.coverage]: fail_under must be a number"
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
        msg = f"[tool.python-qa.record]: {key} must be a non-negative integer"
        raise ConfigError(msg)
    return value
