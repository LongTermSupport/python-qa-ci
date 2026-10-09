"""The external tools python-qa routes: their command lines, configuration and catalogues."""

from __future__ import annotations

import configparser
import contextlib
import fnmatch
import importlib
import io
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from python_qa.config import read_pyproject

if TYPE_CHECKING:
    from collections.abc import Iterator

    from python_qa.config import Config

DEFAULTS = Path(__file__).parent / "defaults"
BUNDLED_PLUGIN = "python_qa.pylint_plugin"
_TEST_DIRECTORIES = frozenset({"test", "tests", "testing"})


@dataclass(frozen=True)
class PylintMessage:
    """One Pylint message python-qa enables, and where it comes from."""

    symbol: str
    msgid: str
    summary: str
    description: str
    origin: str


def ruff_config_args(root: Path) -> list[str]:
    """Return --config for the bundled Ruff configuration, unless the project has its own."""
    own = (root / "ruff.toml").is_file() or (root / ".ruff.toml").is_file()
    if own or "ruff" in read_pyproject(root).get("tool", {}):
        return []
    return ["--config", str(DEFAULTS / "ruff.toml")]


def mypy_config_file(root: Path) -> Path:
    """Return the mypy configuration in force: the project's, or the bundled one."""
    if "mypy" in read_pyproject(root).get("tool", {}):
        return root / "pyproject.toml"
    for name in ("mypy.ini", ".mypy.ini", "setup.cfg"):
        path = root / name
        if path.is_file() and (name != "setup.cfg" or _ini_has_section(path, "mypy")):
            return path
    return DEFAULTS / "mypy.toml"


def mypy_config_args(root: Path) -> list[str]:
    """Return --config-file for the bundled mypy configuration, unless the project has its own."""
    path = mypy_config_file(root)
    return ["--config-file", str(path)] if path.parent == DEFAULTS else []


def uses_own_coverage_config(root: Path) -> bool:
    """Return True when the project configures coverage.py itself."""
    if "coverage" in read_pyproject(root).get("tool", {}) or (root / ".coveragerc").is_file():
        return True
    return any(
        (root / name).is_file() and _ini_has_section(root / name, "coverage:run")
        for name in ("setup.cfg", "tox.ini")
    )


def _ini_has_section(path: Path, section: str) -> bool:
    parser = configparser.ConfigParser()
    with contextlib.suppress(configparser.Error):
        parser.read_string(path.read_text(encoding="utf-8"))
    return parser.has_section(section)


def pylint_args(config: Config) -> list[str]:
    """Return Pylint's options: the bundled rcfile, every plugin, and only their messages."""
    symbols = [message.symbol for message in pylint_messages(config)]
    args = [
        "--rcfile",
        str(DEFAULTS / "pylintrc.toml"),
        "--load-plugins=" + ",".join((BUNDLED_PLUGIN, *config.pylint_plugins)),
        "--disable=all",
        "--enable=" + ",".join(symbols),
        "--score=n",
        "--reports=n",
        "--output-format=text",
    ]
    if config.sensitive_names is not None:
        args.append("--pyqaci-sensitive-names=" + ",".join(config.sensitive_names))
    if config.redacting_types is not None:
        args.append("--pyqaci-redacting-types=" + ",".join(config.redacting_types))
    if config.scan_exclude:
        regexes = (fnmatch.translate(pattern) for pattern in config.scan_exclude)
        args.append("--ignore-paths=" + ",".join(regexes))
    return args


@contextlib.contextmanager
def _project_importable(root: Path) -> Iterator[None]:
    added = [str(root / "src"), str(root)]
    sys.path[:0] = added
    try:
        yield
    finally:
        for entry in added:
            sys.path.remove(entry)


def pylint_messages(config: Config) -> list[PylintMessage]:
    """Return every Pylint message python-qa enables, derived from the loaded checkers."""
    from pylint.lint import PyLinter  # deferred: loading Pylint costs a second at start-up

    plugins = (BUNDLED_PLUGIN, *config.pylint_plugins)
    linter = PyLinter()
    linter.load_default_plugins()
    with _project_importable(config.root):
        for module in plugins:
            _import_plugin(module)
        linter.load_plugin_modules(list(plugins))
    wanted = set(config.pylint_enable)
    messages: list[PylintMessage] = []
    for checker in linter.get_checkers():
        module = type(checker).__module__
        origin = _origin(module, config.pylint_plugins)
        for definition in checker.messages:
            if origin == "pylint" and not {definition.symbol, definition.msgid} & wanted:
                continue
            wanted -= {definition.symbol, definition.msgid}
            messages.append(
                PylintMessage(
                    definition.symbol,
                    definition.msgid,
                    _first_sentence(definition.description),
                    definition.description,
                    origin,
                )
            )
    if wanted:
        msg = f"pylint_enable names no Pylint message: {', '.join(sorted(wanted))}"
        raise ValueError(msg)
    return sorted(messages, key=lambda message: message.symbol)


def _import_plugin(module: str) -> None:
    """Import a plugin so a missing one fails loudly; Pylint records the error and carries on."""
    try:
        importlib.import_module(module)
    except ImportError as error:
        msg = f"pylint plugin {module} cannot be imported: {error}"
        raise ValueError(msg) from error


def _origin(module: str, project_plugins: tuple[str, ...]) -> str:
    if module == BUNDLED_PLUGIN or module.startswith(BUNDLED_PLUGIN + "."):
        return "bundled"
    if any(module == name or module.startswith(name + ".") for name in project_plugins):
        return "project"
    return "pylint"


def _first_sentence(text: str) -> str:
    flat = " ".join(text.split())
    match = re.match(r"(.+?[.!?])(?:\s|$)", flat)
    return match.group(1) if match else flat


def parse_ruff_enabled(text: str) -> list[tuple[str, str]]:
    """Return (code, name) for each rule in `ruff check --show-settings` output's enabled list."""
    rules: list[tuple[str, str]] = []
    inside = False
    for line in text.splitlines():
        if line.startswith("linter.rules.enabled = ["):
            inside = True
        elif inside and line.startswith("]"):
            break
        elif inside and (match := re.match(r"\s*([\w-]+) \(([A-Z]+[0-9]+)\),?$", line)):
            rules.append((match.group(2), match.group(1)))
    return rules


def ruff_enabled_rules(root: Path) -> list[tuple[str, str]]:
    """Return the Ruff rules the project's resolved configuration enables."""
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--show-settings", *ruff_config_args(root)],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return parse_ruff_enabled(result.stdout)


def mypy_enabled_codes(root: Path) -> list[tuple[str, str]]:
    """Return (code, description) for each mypy error code the configuration leaves enabled."""
    from mypy import errorcodes  # deferred: mypy is only needed when listing
    from mypy.config_parser import parse_config_file
    from mypy.options import Options

    options = Options()
    parse_config_file(
        options, lambda: None, str(mypy_config_file(root)), io.StringIO(), io.StringIO()
    )
    problems: list[str] = []
    options.process_error_codes(error_callback=problems.append)
    if problems:
        raise ValueError("; ".join(problems))
    enabled = {
        code
        for code in errorcodes.error_codes.values()
        if (code.default_enabled and code not in options.disabled_error_codes)
        or code in options.enabled_error_codes
    }
    return sorted((code.code, code.description) for code in enabled)


def lane_commands(
    config: Config, *, paths: tuple[str, ...] | None, no_fix: bool
) -> dict[str, list[list[str]]]:
    """Return the commands each external lane runs, in order."""
    python = sys.executable
    targets = list(paths or config.paths)
    check = ["--check", "--diff"] if no_fix else []
    ruff_config = ruff_config_args(config.root)
    return {
        "fmt": [[python, "-m", "ruff", "format", *check, *ruff_config, *targets]],
        "ruff": [
            [
                python,
                "-m",
                "ruff",
                "check",
                "--no-fix",
                "--output-format=concise",
                *ruff_config,
                *targets,
            ]
        ],
        "mypy": [[python, "-m", "mypy", *mypy_config_args(config.root), *targets]],
        "pylint": [[python, "-m", "pylint", *pylint_args(config), *targets]],
        "test": _test_commands(config),
        "audit": [[python, "-m", "pip_audit", "--progress-spinner=off"]],
    }


def _test_commands(config: Config) -> list[list[str]]:
    python = sys.executable
    if not config.tools["coverage"]:
        return [[python, "-m", "pytest"]]
    source: list[str] = []
    if not uses_own_coverage_config(config.root):
        measured = [path for path in config.paths if Path(path).name not in _TEST_DIRECTORIES]
        source = ["--source=" + ",".join(measured)] if measured else []
    return [
        [python, "-m", "coverage", "run", *source, "-m", "pytest"],
        [python, "-m", "coverage", "report", f"--fail-under={config.coverage_fail_under}"],
    ]
