"""Tests for reading [tool.py-qa] from pyproject.toml."""

import re
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


def test_project_checks(tmp_path: Path) -> None:
    write(
        tmp_path,
        """
[[tool.py-qa.check]]
name = "spelling"
command = ["{python}", "scripts/spelling.py"]
description = "Prose is written in British English."
doc = "scripts/spelling.py"
paths = ["**/*.md"]
diff_command = ["{python}", "scripts/spelling.py", "{files}"]

[[tool.py-qa.check]]
name = "smoke"
command = ["scripts/smoke.sh"]
description = "The installed command answers."
doc = "docs/smoke.md"
phase = "runners"
diff = false
verdict = { file = "out/smoke.json", key = "summary.passed" }
""",
    )
    spelling, smoke = load_config(tmp_path).checks
    assert spelling.name == "spelling"
    assert spelling.command == ("{python}", "scripts/spelling.py")
    assert spelling.phase == "detectors"
    assert spelling.paths == ("**/*.md",)
    assert spelling.diff_command == ("{python}", "scripts/spelling.py", "{files}")
    assert smoke.phase == "runners"
    assert smoke.paths is None
    assert smoke.diff_command is None
    assert spelling.in_diff
    assert not smoke.in_diff
    assert spelling.verdict is None
    assert smoke.verdict == ("out/smoke.json", ("summary", "passed"))


CHECK = 'name = "x"\ncommand = ["x"]\ndescription = "X holds."\ndoc = "x.md"\n'


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("[tool.py-qa]\ncheck = 1\n", "array of tables"),
        ("[[tool.py-qa.check]]\n" + CHECK + "other = 1\n", "unknown key other"),
        ("[[tool.py-qa.check]]\n" + CHECK.replace('"x"\ncommand', '"Bad Name"\ncommand'), "name"),
        ("[[tool.py-qa.check]]\n" + CHECK.replace('["x"]', "[]"), "non-empty list"),
        ("[[tool.py-qa.check]]\n" + CHECK.replace('description = "X holds."\n', ""), "description"),
        ("[[tool.py-qa.check]]\n" + CHECK.replace('doc = "x.md"\n', ""), "doc"),
        ("[[tool.py-qa.check]]\n" + CHECK + 'phase = "format"\n', "phase must be"),
        ("[[tool.py-qa.check]]\n" + CHECK + "paths = []\n", "paths"),
        ("[[tool.py-qa.check]]\n" + CHECK + 'diff = "no"\n', "diff must be"),
        ("[[tool.py-qa.check]]\n" + CHECK + 'verdict = "x.json"\n', "verdict must be a table"),
        ("[[tool.py-qa.check]]\n" + CHECK + 'verdict = { file = "x.json" }\n', "verdict must name"),
        ("[[tool.py-qa.check]]\n" + CHECK + 'verdict = { file = "x", key = "" }\n', "verdict"),
        ("[[tool.py-qa.check]]\n" + CHECK.replace('"x"\ncommand', '"ruff"\ncommand'), "lane"),
        ("[[tool.py-qa.check]]\n" + CHECK + "[[tool.py-qa.check]]\n" + CHECK, "twice"),
        ("[[tool.py-qa.check]]\n" + CHECK + 'diff_command = ["x", "{nope}"]\n', "{nope}"),
    ],
)
def test_rejects_bad_project_checks(tmp_path: Path, text: str, fragment: str) -> None:
    write(tmp_path, text)
    with pytest.raises(ConfigError, match=re.escape(fragment)):
        load_config(tmp_path)


def test_diff_policy_defaults_and_keys(tmp_path: Path) -> None:
    write(tmp_path, "")
    default = load_config(tmp_path).diff
    assert default.base is None
    assert default.unmapped == "full"
    assert "pyproject.toml" in default.full_tests_on
    write(
        tmp_path,
        """
[tool.py-qa.diff]
base = "origin/develop"
unmapped = "ignore"
full_tests_on = ["setup.py"]

[[tool.py-qa.diff.map]]
glob = "docs/**/*.md"
tests = ["tests/test_docs.py"]

[[tool.py-qa.diff.map]]
glob = "*.txt"
tests = []
exclude = ["notes/*.txt"]
why = "nothing reads them"
""",
    )
    diff = load_config(tmp_path).diff
    assert diff.base == "origin/develop"
    assert diff.unmapped == "ignore"
    assert diff.full_tests_on == ("setup.py",)
    assert [(entry.glob, entry.tests, entry.exclude) for entry in diff.map] == [
        ("docs/**/*.md", ("tests/test_docs.py",), ()),
        ("*.txt", (), ("notes/*.txt",)),
    ]
    assert diff.map[1].why == "nothing reads them"


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("[tool.py-qa.diff]\nother = 1\n", "unknown key"),
        ('[tool.py-qa.diff]\nunmapped = "fail"\n', "unmapped must be"),
        ("[[tool.py-qa.diff.map]]\ntests = []\n", "glob"),
        ('[[tool.py-qa.diff.map]]\nglob = "x"\n', "tests"),
        ('[[tool.py-qa.diff.map]]\nglob = "x"\ntests = []\nwhy = 3\n', "why"),
    ],
)
def test_rejects_bad_diff_policy(tmp_path: Path, text: str, fragment: str) -> None:
    write(tmp_path, text)
    with pytest.raises(ConfigError, match=re.escape(fragment)):
        load_config(tmp_path)


def test_test_diff_command_setup_lock_and_rule_doc_command(tmp_path: Path) -> None:
    write(tmp_path, "")
    config = load_config(tmp_path)
    assert config.test_diff_command is None
    assert config.test_setup == ()
    assert config.lock is True
    assert config.lock_path is None
    assert config.rule_doc_command is None
    write(
        tmp_path,
        """
[tool.py-qa]
lock = "untracked/qa.lock"
rule_doc_command = ["scripts/explain.py", "{identifier}"]

[tool.py-qa.test]
command = ["scripts/test.sh"]
diff_command = ["scripts/test.sh", "{tests}"]
setup = [["scripts/start-db.sh"], ["scripts/seed.sh", "--quick"]]
verdict = { file = "out/tests.json", key = "summary.passed_all" }
diff_verdict = { file = "out/some.json", key = "ok" }
""",
    )
    config = load_config(tmp_path)
    assert config.test_diff_command == ("scripts/test.sh", "{tests}")
    assert config.test_setup == (("scripts/start-db.sh",), ("scripts/seed.sh", "--quick"))
    assert config.test_verdict == ("out/tests.json", ("summary", "passed_all"))
    assert config.test_diff_verdict == ("out/some.json", ("ok",))
    assert config.lock is True
    assert config.lock_path == "untracked/qa.lock"
    assert config.rule_doc_command == ("scripts/explain.py", "{identifier}")
    write(tmp_path, "[tool.py-qa]\nlock = false\n")
    assert load_config(tmp_path).lock is False


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("[tool.py-qa]\nlock = 3\n", "lock must be"),
        ('[tool.py-qa]\nrule_doc_command = ["x"]\n', "{identifier}"),
        ('[tool.py-qa.test]\ndiff_command = ["pytest"]\n', "{tests}"),
        ("[tool.py-qa.test]\nsetup = [[]]\n", "setup"),
        ('[tool.py-qa.test]\nsetup = ["x"]\n', "setup"),
    ],
)
def test_rejects_bad_test_lock_and_rule_doc(tmp_path: Path, text: str, fragment: str) -> None:
    write(tmp_path, text)
    with pytest.raises(ConfigError, match=re.escape(fragment)):
        load_config(tmp_path)
