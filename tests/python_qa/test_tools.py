"""Tests for how python-qa composes each external tool's command line and reads its catalogue."""

import sys
from pathlib import Path

import pytest

from python_qa.config import load_config
from python_qa.tools import (
    DEFAULTS,
    lane_commands,
    mypy_config_args,
    mypy_enabled_codes,
    parse_ruff_enabled,
    pylint_args,
    pylint_messages,
    ruff_config_args,
    ruff_enabled_rules,
    uses_own_coverage_config,
)


def write(root: Path, name: str, text: str) -> None:
    (root / name).write_text(text, encoding="utf-8")


def test_bundled_defaults_ship_with_the_package() -> None:
    for name in ("ruff.toml", "mypy.toml", "pylintrc.toml"):
        assert (DEFAULTS / name).is_file()


def test_ruff_uses_bundled_config_only_when_the_project_has_none(tmp_path: Path) -> None:
    assert ruff_config_args(tmp_path) == ["--config", str(DEFAULTS / "ruff.toml")]
    write(tmp_path, "pyproject.toml", "[tool.ruff]\nline-length = 100\n")
    assert ruff_config_args(tmp_path) == []


def test_ruff_toml_counts_as_project_config(tmp_path: Path) -> None:
    write(tmp_path, ".ruff.toml", "")
    assert ruff_config_args(tmp_path) == []


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("pyproject.toml", "[tool.mypy]\nstrict = true\n"),
        ("mypy.ini", "[mypy]\n"),
        (".mypy.ini", "[mypy]\n"),
        ("setup.cfg", "[mypy]\n"),
    ],
)
def test_mypy_project_config(tmp_path: Path, name: str, text: str) -> None:
    write(tmp_path, name, text)
    assert mypy_config_args(tmp_path) == []


def test_mypy_bundled_config(tmp_path: Path) -> None:
    write(tmp_path, "setup.cfg", "[metadata]\nname = x\n")
    assert mypy_config_args(tmp_path) == ["--config-file", str(DEFAULTS / "mypy.toml")]


def test_pylint_args_load_bundled_and_project_plugins(tmp_path: Path) -> None:
    write(
        tmp_path,
        "pyproject.toml",
        '[tool.python-qa]\npylint_enable = ["unspecified-encoding"]\n'
        '[tool.python-qa.sensitive_repr]\nnames = ["pin"]\nredacting_types = ["Sealed"]\n',
    )
    args = pylint_args(load_config(tmp_path))
    assert args[:2] == ["--rcfile", str(DEFAULTS / "pylintrc.toml")]
    assert "--load-plugins=python_qa.pylint_plugin" in args
    assert "--disable=all" in args
    enable = next(arg for arg in args if arg.startswith("--enable="))
    assert set(enable.removeprefix("--enable=").split(",")) == {
        "pyqaci-sensitive-repr",
        "pyqaci-broad-suppress",
        "unspecified-encoding",
    }
    assert "--pyqaci-sensitive-names=pin" in args
    assert "--pyqaci-redacting-types=Sealed" in args


def test_pylint_messages_name_their_origin(tmp_path: Path) -> None:
    write(
        tmp_path, "pyproject.toml", '[tool.python-qa]\npylint_enable = ["unspecified-encoding"]\n'
    )
    messages = {m.symbol: m for m in pylint_messages(load_config(tmp_path))}
    assert messages["pyqaci-sensitive-repr"].origin == "bundled"
    assert messages["pyqaci-sensitive-repr"].msgid == "W9701"
    assert messages["unspecified-encoding"].origin == "pylint"
    assert messages["unspecified-encoding"].summary


def test_pylint_rejects_an_unknown_enable(tmp_path: Path) -> None:
    write(tmp_path, "pyproject.toml", '[tool.python-qa]\npylint_enable = ["no-such-message"]\n')
    with pytest.raises(ValueError, match="no-such-message"):
        pylint_messages(load_config(tmp_path))


def test_parse_ruff_enabled() -> None:
    text = (
        "linter.exclude = []\n"
        "linter.rules.enabled = [\n"
        "\tmutable-argument-default (B006),\n"
        "\tsyntax-error,\n"
        "\tio-error (E902),\n"
        "]\n"
        "linter.rules.should_fix = [\n"
        "\tother (X1),\n"
        "]\n"
    )
    assert parse_ruff_enabled(text) == [("B006", "mutable-argument-default"), ("E902", "io-error")]


def test_ruff_enabled_rules_follow_the_configuration(tmp_path: Path) -> None:
    write(tmp_path, "pyproject.toml", '[tool.ruff.lint]\nselect = ["F401"]\n')
    assert ruff_enabled_rules(tmp_path) == [("F401", "unused-import")]


def test_mypy_enabled_codes_follow_the_configuration(tmp_path: Path) -> None:
    write(
        tmp_path,
        "pyproject.toml",
        '[tool.mypy]\ndisable_error_code = ["misc"]\nenable_error_code = ["truthy-bool"]\n',
    )
    codes = {code for code, _ in mypy_enabled_codes(tmp_path)}
    assert "arg-type" in codes
    assert "truthy-bool" in codes
    assert "misc" not in codes


def test_coverage_config_detection(tmp_path: Path) -> None:
    assert not uses_own_coverage_config(tmp_path)
    write(tmp_path, "pyproject.toml", "[tool.coverage.run]\nbranch = true\n")
    assert uses_own_coverage_config(tmp_path)


def test_lane_commands(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    config = load_config(tmp_path)
    python = sys.executable
    commands = lane_commands(config, paths=None, no_fix=True)
    assert commands["fmt"] == [
        [
            python,
            "-m",
            "ruff",
            "format",
            "--check",
            "--diff",
            *ruff_config_args(tmp_path),
            "src",
            "tests",
        ]
    ]
    assert commands["ruff"][0][:5] == [python, "-m", "ruff", "check", "--no-fix"]
    assert commands["mypy"] == [[python, "-m", "mypy", *mypy_config_args(tmp_path), "src", "tests"]]
    assert commands["test"] == [
        [python, "-m", "coverage", "run", "--source=src", "-m", "pytest"],
        [python, "-m", "coverage", "report", "--fail-under=80.0"],
    ]
    fixing = lane_commands(config, paths=("src/a.py",), no_fix=False)
    assert fixing["fmt"] == [
        [python, "-m", "ruff", "format", *ruff_config_args(tmp_path), "src/a.py"]
    ]


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("pyproject.toml", "[tool.coverage.report]\nfail_under = 95\n"),
        (".coveragerc", "[report]\nfail_under = 95\n"),
        ("setup.cfg", "[coverage:report]\nfail_under = 95\n"),
        ("tox.ini", "[coverage:report]\nfail_under = 95\n"),
    ],
)
def test_projects_own_coverage_floor_is_not_overridden(
    tmp_path: Path, name: str, text: str
) -> None:
    write(tmp_path, name, text)
    commands = lane_commands(load_config(tmp_path), paths=None, no_fix=True)
    assert commands["test"][1] == [sys.executable, "-m", "coverage", "report"]


def test_black_formatter(tmp_path: Path) -> None:
    write(tmp_path, "pyproject.toml", '[tool.python-qa]\nformatter = "black"\npaths = ["pkg"]\n')
    config = load_config(tmp_path)
    checking = lane_commands(config, paths=None, no_fix=True)["fmt"]
    fixing = lane_commands(config, paths=None, no_fix=False)["fmt"]
    assert checking == [[sys.executable, "-m", "black", "--check", "--diff", "pkg"]]
    assert fixing == [[sys.executable, "-m", "black", "pkg"]]


def test_test_lane_without_coverage(tmp_path: Path) -> None:
    write(tmp_path, "pyproject.toml", "[tool.python-qa.tools]\ncoverage = false\n")
    commands = lane_commands(load_config(tmp_path), paths=None, no_fix=True)
    assert commands["test"] == [[sys.executable, "-m", "pytest"]]
