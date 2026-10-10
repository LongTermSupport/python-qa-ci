"""Tests for reading [tool.py-qa] from pyproject.toml."""

from pathlib import Path

import pytest

from py_qa.config import TOOLS, ConfigError, load_config


def write(root: Path, text: str) -> None:
    (root / "pyproject.toml").write_text(text, encoding="utf-8")


def test_defaults_without_a_table(tmp_path: Path) -> None:
    write(tmp_path, '[project]\nname = "x"\n')
    config = load_config(tmp_path)
    assert config.record.path == "qa/record.toml"
    assert config.docs_dir == "docs/defences"
    assert config.paths == (".",)
    assert config.tools["audit"] is False
    assert all(config.tools[name] for name in TOOLS if name != "audit")
    assert config.summary_file is None
    assert config.formatter == "ruff"


def test_default_paths_are_src_and_tests_when_present(tmp_path: Path) -> None:
    write(tmp_path, "")
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    assert load_config(tmp_path).paths == ("src", "tests")


def test_no_pyproject_is_the_defaults(tmp_path: Path) -> None:
    assert load_config(tmp_path).paths == (".",)


def test_reads_every_documented_key(tmp_path: Path) -> None:
    write(
        tmp_path,
        """
[tool.py-qa]
docs_dir = "docs/rules"
paths = ["pkg"]
scan_exclude = ["pkg/generated/**"]
pylint_plugins = ["pkg.checkers"]
pylint_enable = ["unspecified-encoding"]

[tool.py-qa.record]
path = "qa/exceptions.toml"
max_total = 4
max_per_rule = 2
max_review_days = 90

[tool.py-qa.tools]
mypy = false
audit = true

[tool.py-qa.coverage]
fail_under = 95

[tool.py-qa.summary]
file = "AGENTS.md"

[tool.py-qa.sensitive_repr]
names = ["pin"]
redacting_types = ["Sealed"]
""",
    )
    config = load_config(tmp_path)
    assert config.docs_dir == "docs/rules"
    assert config.paths == ("pkg",)
    assert config.scan_exclude == ("pkg/generated/**",)
    assert config.pylint_plugins == ("pkg.checkers",)
    assert config.pylint_enable == ("unspecified-encoding",)
    assert config.record.path == "qa/exceptions.toml"
    assert config.record.max_total == 4
    assert config.record.max_per_rule == 2
    assert config.record.max_review_days == 90
    assert config.tools["mypy"] is False
    assert config.tools["audit"] is True
    assert config.coverage_fail_under == 95
    assert config.summary_file == "AGENTS.md"
    assert config.sensitive_names == ("pin",)
    assert config.redacting_types == ("Sealed",)


def test_record_shorthand(tmp_path: Path) -> None:
    write(tmp_path, '[tool.py-qa]\nrecord = "exceptions.toml"\n')
    assert load_config(tmp_path).record.path == "exceptions.toml"


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("[tool.py-qa]\nunknown = 1\n", "unknown key"),
        ("[tool.py-qa.tools]\nnope = true\n", "unknown tool"),
        ("[tool.py-qa.tools]\nmypy = 1\n", "must be true or false"),
        ('[tool.py-qa]\npaths = "src"\n', "list of strings"),
        ("[tool.py-qa.record]\nmax_total = -1\n", "non-negative integer"),
        ('[tool.py-qa.coverage]\nfail_under = "x"\n', "number"),
        ("[tool.py-qa.summary]\nfile = 3\n", "string"),
        ("[tool.py-qa.sensitive_repr]\nother = []\n", "unknown key"),
        ("[tool.py-qa]\nrecord = 3\n", "must be a table"),
        ('[tool.py-qa]\nformatter = "yapf"\n', "formatter must be"),
        ("[tool.py-qa\n", "cannot parse"),
        ("[tool.python-qa]\npaths = []\n", r"renamed \[tool.py-qa\]"),
    ],
)
def test_rejects_bad_configuration(tmp_path: Path, text: str, fragment: str) -> None:
    write(tmp_path, text)
    with pytest.raises(ConfigError, match=fragment):
        load_config(tmp_path)


def test_test_command_and_lane_paths(tmp_path: Path) -> None:
    write(
        tmp_path,
        '[tool.py-qa.test]\ncommand = ["make", "test"]\n'
        '[tool.py-qa.lane_paths]\nmypy = ["src"]\nfmt = ["."]\n',
    )
    config = load_config(tmp_path)
    assert config.test_command == ("make", "test")
    assert config.lane_paths == {"mypy": ("src",), "fmt": (".",)}


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("[tool.py-qa.test]\ncommand = []\n", "non-empty list of strings"),
        ('[tool.py-qa.test]\ncommand = "make test"\n', "non-empty list of strings"),
        ("[tool.py-qa.test]\nother = 1\n", "unknown key"),
        ('[tool.py-qa.lane_paths]\ntest = ["src"]\n', "unknown lane test"),
        ('[tool.py-qa.lane_paths]\nmypy = "src"\n', "list of strings"),
    ],
)
def test_rejects_bad_test_and_lane_paths(tmp_path: Path, text: str, fragment: str) -> None:
    write(tmp_path, text)
    with pytest.raises(ConfigError, match=fragment):
        load_config(tmp_path)
