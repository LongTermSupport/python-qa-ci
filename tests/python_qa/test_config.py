"""Tests for reading [tool.python-qa] from pyproject.toml."""

from pathlib import Path

import pytest

from python_qa.config import TOOLS, ConfigError, load_config


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
[tool.python-qa]
docs_dir = "docs/rules"
paths = ["pkg"]
scan_exclude = ["pkg/generated/**"]
pylint_plugins = ["pkg.checkers"]
pylint_enable = ["unspecified-encoding"]

[tool.python-qa.record]
path = "qa/exceptions.toml"
max_total = 4
max_per_rule = 2
max_review_days = 90

[tool.python-qa.tools]
mypy = false
audit = true

[tool.python-qa.coverage]
fail_under = 95

[tool.python-qa.summary]
file = "AGENTS.md"

[tool.python-qa.sensitive_repr]
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
    write(tmp_path, '[tool.python-qa]\nrecord = "exceptions.toml"\n')
    assert load_config(tmp_path).record.path == "exceptions.toml"


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("[tool.python-qa]\nunknown = 1\n", "unknown key"),
        ("[tool.python-qa.tools]\nnope = true\n", "unknown tool"),
        ("[tool.python-qa.tools]\nmypy = 1\n", "must be true or false"),
        ('[tool.python-qa]\npaths = "src"\n', "list of strings"),
        ("[tool.python-qa.record]\nmax_total = -1\n", "non-negative integer"),
        ('[tool.python-qa.coverage]\nfail_under = "x"\n', "number"),
        ("[tool.python-qa.summary]\nfile = 3\n", "string"),
        ("[tool.python-qa.sensitive_repr]\nother = []\n", "unknown key"),
        ("[tool.python-qa]\nrecord = 3\n", "must be a table"),
        ("[tool.python-qa\n", "cannot parse"),
    ],
)
def test_rejects_bad_configuration(tmp_path: Path, text: str, fragment: str) -> None:
    write(tmp_path, text)
    with pytest.raises(ConfigError, match=fragment):
        load_config(tmp_path)
