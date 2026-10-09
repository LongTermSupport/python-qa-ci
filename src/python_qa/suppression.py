"""Every route that silences a detector, found in comments and configuration, held to the record.

Comments are read with tokenize, so a directive inside a string or a docstring is not one. Each
site names the tool it silences and the identifiers it names; a site that names none silences
everything and can never be recorded.
"""

from __future__ import annotations

import configparser
import fnmatch
import io
import re
import subprocess
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomllib

from python_qa.config import ConfigError, read_pyproject
from python_qa.finding import Finding
from python_qa.record import STALE, RecordEntry

UNRECORDED = "pyqaci.suppression.unrecorded"
BLANKET = "pyqaci.suppression.blanket"
UNSCANNED = "pyqaci.suppression.unscanned"

SKIPPED_DIRECTORIES = frozenset(
    {
        ".git",
        ".hg",
        ".venv",
        "venv",
        ".tox",
        ".nox",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "site-packages",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
    }
)


@dataclass(frozen=True)
class Site:
    """One place that silences a tool: the identifiers it names, or none for a blanket."""

    path: str
    line: int
    tool: str
    codes: tuple[str, ...]
    detail: str = ""

    @property
    def rule_ids(self) -> tuple[str, ...]:
        """Return the record identifiers this site needs, one per code."""
        return tuple(f"{self.tool}::{code}" for code in self.codes)


_RUFF_CODES = r"[A-Z]+[0-9]+(?:[\s,]+[A-Z]+[0-9]+)*"
_FILE_NOQA = re.compile(r"#\s*(?:ruff|flake8)\s*:\s*(?i:noqa)(?:\s*:\s*(" + _RUFF_CODES + "))?")
_NOQA = re.compile(
    r"#\s*(?i:noqa)(?:(?=\s*$)|(?=\s*#)|(?=\s+[^:\s])|\s*:\s*(" + _RUFF_CODES + ")?)"
)
_RUFF_BRACKET = re.compile(r"#\s*ruff\s*:\s*(?:ignore|file-ignore|disable)\[([^\]]*)\]")
_ISORT = re.compile(r"#\s*isort\s*:\s*(?:skip_file|skip|off)\b")
_PYLINT = re.compile(
    r"#\s*pylint\s*:\s*(disable-next|disable-line|disable|skip-file)(?![\w-])(?:\s*=\s*(.*))?"
)
_TYPE_IGNORE = re.compile(r"#\s*type\s*:\s*ignore(?:\[([^\]]*)\])?(?![\w-])")
_MYPY = re.compile(r"#\s*mypy\s*:\s*(.*)")
_PYRIGHT_IGNORE = re.compile(r"#\s*pyright\s*:\s*ignore(?:\[([^\]]*)\])?")
_PYRIGHT = re.compile(r"#\s*pyright\s*:\s*(.*)")
_NOSEC = re.compile(r"#\s*nosec\b(?:\s*:?\s*([A-Z][0-9]+(?:[\s,]+[A-Z][0-9]+)*))?")
_NOSEMGREP = re.compile(r"#\s*nosemgrep\b(?:\s*:\s*([\w.\-]+(?:\s*,\s*[\w.\-]+)*))?")

# A file-level mypy setting relaxes a check when it allows, ignores or turns a warning off.
_MYPY_RELAXING = re.compile(r"^(?:allow|ignore|no)-[a-z-]+$")


def _split(codes: str | None, separators: str = r"[\s,]+") -> tuple[str, ...]:
    if not codes:
        return ()
    return tuple(code for code in re.split(separators, codes.strip()) if code)


def _directives(segment: str) -> list[tuple[str, tuple[str, ...]]]:
    """Return (tool, codes) for one '#'-led segment of a comment; codes empty means blanket."""
    if match := _FILE_NOQA.match(segment):
        return [("ruff", _split(match.group(1)))]
    if match := _NOQA.match(segment):
        return [("ruff", _split(match.group(1)))]
    if match := _RUFF_BRACKET.match(segment):
        return [("ruff", _split(match.group(1), r"\s*,\s*"))]
    if _ISORT.match(segment):
        return [("ruff", ("I001",))]
    if match := _PYLINT.match(segment):
        codes = _split(match.group(2), r"\s*,\s*") if match.group(1) != "skip-file" else ()
        return [("pylint", () if "all" in codes else codes)]
    if match := _TYPE_IGNORE.match(segment):
        return [("mypy", _split(match.group(1), r"\s*,\s*"))]
    if match := _MYPY.match(segment):
        return _mypy_inline(match.group(1))
    if match := _PYRIGHT_IGNORE.match(segment):
        return [("pyright", _split(match.group(1), r"\s*,\s*"))]
    if match := _PYRIGHT.match(segment):
        return _pyright_inline(match.group(1))
    if match := _NOSEC.match(segment):
        return [("bandit", _split(match.group(1)))]
    if match := _NOSEMGREP.match(segment):
        return [("semgrep", _split(match.group(1), r"\s*,\s*"))]
    return []


def _mypy_inline(settings: str) -> list[tuple[str, tuple[str, ...]]]:
    found: list[tuple[str, tuple[str, ...]]] = []
    for raw in re.split(r",(?=\s*[a-z-]+\s*(?:=|,|$))", settings):
        name, _, value = raw.strip().partition("=")
        name = name.strip()
        if name == "ignore-errors":
            found.append(("mypy", ()))
        elif name == "disable-error-code":
            found.append(("mypy", _split(value.strip().strip("\"'"), r"\s*,\s*")))
        elif _MYPY_RELAXING.match(name):
            found.append(("mypy", (name,)))
    return found


def _pyright_inline(settings: str) -> list[tuple[str, tuple[str, ...]]]:
    found: list[tuple[str, tuple[str, ...]]] = []
    for raw in settings.split(","):
        name, _, value = raw.strip().partition("=")
        name, value = name.strip(), value.strip().strip("\"'").lower()
        if name == "basic":
            found.append(("pyright", ("basic",)))
        elif name.startswith("report") and value in {"false", "none", "information", "warning"}:
            found.append(("pyright", (name,)))
    return found


def comment_sites(display: str, source: str) -> list[Site]:
    """Return every suppression directive in source's comments; raise SyntaxError if unreadable."""
    found: list[Site] = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError) as error:
        raise SyntaxError(str(error)) from error
    for token in tokens:
        if token.type != tokenize.COMMENT:
            continue
        for segment in re.split(r"(?=#)", token.string):
            found.extend(
                Site(display, token.start[0], tool, codes, segment.strip())
                for tool, codes in _directives(segment)
            )
    return found


def config_sites(root: Path) -> list[Site]:
    """Return every configuration setting that silences Ruff or mypy, in the files they read."""
    found: list[Site] = []
    tool = read_pyproject(root).get("tool", {})
    text = _text(root / "pyproject.toml")
    if isinstance(tool.get("ruff"), dict):
        found.extend(_ruff_sites("pyproject.toml", tool["ruff"], text))
    for name in ("ruff.toml", ".ruff.toml"):
        path = root / name
        if path.is_file():
            found.extend(_ruff_sites(name, _toml(path), _text(path)))
    if isinstance(tool.get("mypy"), dict):
        mypy = tool["mypy"]
        sections = [mypy, *[o for o in mypy.get("overrides", []) if isinstance(o, dict)]]
        for section in sections:
            found.extend(_mypy_sites("pyproject.toml", section, text))
    for name in ("mypy.ini", ".mypy.ini", "setup.cfg"):
        path = root / name
        if path.is_file():
            found.extend(_mypy_ini_sites(name, path))
    return found


def _toml(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        msg = f"{path.name}: cannot parse: {error}"
        raise ConfigError(msg) from error


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _line(text: str, *needles: str) -> int:
    for number, line in enumerate(text.splitlines(), start=1):
        if any(needle in line for needle in needles):
            return number
    return 0


def _ruff_sites(display: str, table: dict[str, Any], text: str) -> list[Site]:
    found: list[Site] = []
    lint = table.get("lint", {}) if isinstance(table.get("lint"), dict) else {}
    for section in (table, lint):
        for key in ("ignore", "extend-ignore"):
            found.extend(
                Site(display, _line(text, f'"{code}"', f"'{code}'"), "ruff", (code,), key)
                for code in section.get(key, [])
            )
        for key in ("per-file-ignores", "extend-per-file-ignores"):
            for pattern, codes in section.get(key, {}).items():
                found.extend(
                    Site(
                        display,
                        _line(text, f'"{code}"', f"'{code}'"),
                        "ruff",
                        (code,),
                        f"{key} {pattern}",
                    )
                    for code in codes
                )
        for key in ("exclude", "extend-exclude"):
            if section.get(key):
                patterns = ", ".join(section[key])
                found.append(Site(display, _line(text, key), "ruff", ("exclude",), patterns))
    return found


def _mypy_sites(display: str, section: dict[str, Any], text: str) -> list[Site]:
    found: list[Site] = []
    codes = section.get("disable_error_code", [])
    if isinstance(codes, str):
        codes = _split(codes, r"\s*,\s*")
    found.extend(
        Site(display, _line(text, "disable_error_code"), "mypy", (code,), "disable_error_code")
        for code in codes
    )
    module = str(section.get("module", "every module"))
    found.extend(
        Site(display, _line(text, key), "mypy", (key,), module)
        for key in ("ignore_errors", "ignore_missing_imports")
        if section.get(key) is True
    )
    if section.get("exclude"):
        found.append(Site(display, _line(text, "exclude"), "mypy", ("exclude",), "exclude"))
    if section.get("follow_imports") in {"skip", "silent"}:
        found.append(
            Site(display, _line(text, "follow_imports"), "mypy", ("follow_imports",), module)
        )
    return found


def _mypy_ini_sites(display: str, path: Path) -> list[Site]:
    parser = configparser.ConfigParser()
    try:
        parser.read_string(path.read_text(encoding="utf-8"))
    except configparser.Error as error:
        msg = f"{display}: cannot parse: {error}"
        raise ConfigError(msg) from error
    text = _text(path)
    found: list[Site] = []
    for name in parser.sections():
        if name != "mypy" and not name.startswith("mypy-"):
            continue
        section = parser[name]
        converted: dict[str, Any] = {"module": name.removeprefix("mypy-")}
        for key in ("ignore_errors", "ignore_missing_imports"):
            if key in section:
                converted[key] = section.getboolean(key)
        for key in ("disable_error_code", "exclude", "follow_imports"):
            if key in section:
                converted[key] = section[key]
        found.extend(_mypy_sites(display, converted, text))
    return found


def project_files(root: Path, scan_exclude: tuple[str, ...]) -> list[str]:
    """Return the project's Python files, relative and sorted, honouring .gitignore and excludes."""
    listed = _git_files(root)
    if listed is None:
        listed = [
            path.relative_to(root).as_posix()
            for path in root.rglob("*.py*")
            if path.suffix in {".py", ".pyi"}
            and not SKIPPED_DIRECTORIES.intersection(path.relative_to(root).parts)
        ]
    return sorted(
        name
        for name in listed
        if not any(fnmatch.fnmatchcase(name, pattern) for pattern in scan_exclude)
        and (root / name).is_file()
    )


def within(name: str, path: str) -> bool:
    """Return True when the relative file name is path itself or lies below it."""
    prefix = path.rstrip("/")
    return prefix in {"", "."} or name == prefix or name.startswith(prefix + "/")


def scope_files(root: Path, scan_exclude: tuple[str, ...], paths: tuple[str, ...]) -> list[str]:
    """Return the project's Python files under paths, listed one by one.

    A detector handed a directory decides for itself which files it contains; Pylint walks only
    importable packages and skips a directory without an __init__.py below one. Naming every
    file makes the detector's scope the sweep scope.
    """
    return [
        name
        for name in project_files(root, scan_exclude)
        if any(within(name, path) for path in paths)
    ]


def _git_files(root: Path) -> list[str] | None:
    if not (root / ".git").exists():
        return None
    result = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            "*.py",
            "*.pyi",
        ],
        capture_output=True,
        check=True,
    )
    return sorted({name for name in result.stdout.decode().split("\0") if name})


def check_suppressions(
    sites: list[Site], entries: list[RecordEntry], *, full_scan: bool
) -> list[Finding]:
    """Hold every site to the record; on a full scan, report entries that cover nothing."""
    findings: list[Finding] = []
    recorded = {(entry.rule, entry.path) for entry in entries}
    used: set[tuple[str, str]] = set()
    for site in sites:
        if not site.codes:
            findings.append(
                Finding(
                    site.path,
                    site.line,
                    BLANKET,
                    f"{site.tool} is silenced here for every identifier; name the identifier and "
                    "record the exception",
                )
            )
            continue
        for rule in site.rule_ids:
            if (rule, site.path) in recorded:
                used.add((rule, site.path))
                continue
            findings.append(
                Finding(
                    site.path,
                    site.line,
                    UNRECORDED,
                    f"{rule} is suppressed here with no exception in the project record",
                )
            )
    if full_scan:
        findings.extend(
            Finding(
                entry.path,
                0,
                STALE,
                f"exception #{entry.number} ({entry.rule}) covers no suppression; remove it",
            )
            for entry in entries
            if (entry.rule, entry.path) not in used
        )
    return findings
