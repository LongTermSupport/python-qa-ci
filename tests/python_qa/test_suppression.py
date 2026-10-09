"""Tests for the suppression scan: every route that silences a detector without the record.

The sources below spell each directive with "#@" for "# " and "#!" for a bare "#", so this file
holds no directive of its own for any tool or editor hook to act on.
"""

import subprocess
from datetime import date
from pathlib import Path

import pytest

from python_qa.record import RecordEntry
from python_qa.suppression import (
    Site,
    check_suppressions,
    comment_sites,
    config_sites,
    project_files,
)

REASON = "The fixture deliberately holds the construction so the rule's red proof has a target."


def source(text: str) -> str:
    return text.replace("#@", "# ").replace("#!", "#")


def sites(text: str) -> list[tuple[int, str, tuple[str, ...]]]:
    return [(site.line, site.tool, site.codes) for site in comment_sites("a.py", source(text))]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("x = 1  #@noqa\n", [(1, "ruff", ())]),
        ("x = 1  #!NOQA:E501\n", [(1, "ruff", ("E501",))]),
        ("x = 1  #@noqa: E741, F841 because\n", [(1, "ruff", ("E741", "F841"))]),
        ("#@ruff: noqa\n", [(1, "ruff", ())]),
        ("#@flake8: noqa: F401\n", [(1, "ruff", ("F401",))]),
        ("#@ruff: ignore[ARG001, E501,]\n", [(1, "ruff", ("ARG001", "E501"))]),
        ("#@ruff: file-ignore[F401]\n", [(1, "ruff", ("F401",))]),
        ("#@ruff: disable[E501]\n#@ruff: enable[E501]\n", [(1, "ruff", ("E501",))]),
        ("import os  #@isort: skip\n", [(1, "ruff", ("I001",))]),
        ("#@isort: skip_file\n", [(1, "ruff", ("I001",))]),
        (
            "x = 1  #@pylint: disable=invalid-name, W0612\n",
            [(1, "pylint", ("invalid-name", "W0612"))],
        ),
        ("#@pylint:disable-next=too-many-locals\n", [(1, "pylint", ("too-many-locals",))]),
        ("#@pylint: disable=all\n", [(1, "pylint", ())]),
        ("#@pylint: skip-file\n", [(1, "pylint", ())]),
        ("x = 1  #@type: ignore\n", [(1, "mypy", ())]),
        ("x = 1  #@type: ignore[arg-type, misc]\n", [(1, "mypy", ("arg-type", "misc"))]),
        ("#@mypy: ignore-errors\n", [(1, "mypy", ())]),
        (
            '#@mypy: disable-error-code="no-untyped-def, misc"\n',
            [(1, "mypy", ("no-untyped-def", "misc"))],
        ),
        ("#@mypy: allow-untyped-defs\n", [(1, "mypy", ("allow-untyped-defs",))]),
        ("#@mypy: warn-unreachable\n", []),
        ("x = 1  #@pyright: ignore\n", [(1, "pyright", ())]),
        (
            "x = 1  #@pyright: ignore[reportGeneralTypeIssues]\n",
            [(1, "pyright", ("reportGeneralTypeIssues",))],
        ),
        ("#@pyright: reportMissingImports=false\n", [(1, "pyright", ("reportMissingImports",))]),
        ("#@pyright: basic\n", [(1, "pyright", ("basic",))]),
        ("#@pyright: strict\n", []),
        ("x = 1  #@nosec\n", [(1, "bandit", ())]),
        ("x = 1  #@nosec B602, B607\n", [(1, "bandit", ("B602", "B607"))]),
        ("x = 1  #@nosemgrep\n", [(1, "semgrep", ())]),
        (
            "x = 1  #@nosemgrep: python.lang.rule-a\n",
            [(1, "semgrep", ("python.lang.rule-a",))],
        ),
        (
            "x = 1  #@type: ignore[misc]  #@noqa: E501\n",
            [(1, "mypy", ("misc",)), (1, "ruff", ("E501",))],
        ),
        ('x = "#@noqa"\n"""\n#@type: ignore\n"""\n', []),
        ("x = 1  #@this mentions noqa in prose\n", []),
    ],
)
def test_comment_forms(text: str, expected: list[tuple[int, str, tuple[str, ...]]]) -> None:
    assert sites(text) == expected


def test_unparseable_source_raises() -> None:
    with pytest.raises(SyntaxError):
        comment_sites("a.py", 'x = """\n')


def write(root: Path, name: str, text: str) -> None:
    (root / name).write_text(text, encoding="utf-8")


def test_pyproject_routes(tmp_path: Path) -> None:
    write(
        tmp_path,
        "pyproject.toml",
        """
[tool.ruff]
extend-exclude = ["gen"]
ignore = ["E741"]

[tool.ruff.lint]
ignore = ["E501"]
extend-ignore = ["B008"]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101"]

[tool.mypy]
strict = true
disable_error_code = ["misc"]
exclude = ["build/"]

[[tool.mypy.overrides]]
module = "vendor.*"
ignore_errors = true
ignore_missing_imports = true
follow_imports = "skip"
""",
    )
    found = {(site.tool, site.codes) for site in config_sites(tmp_path)}
    assert found == {
        ("ruff", ("exclude",)),
        ("ruff", ("E741",)),
        ("ruff", ("E501",)),
        ("ruff", ("B008",)),
        ("ruff", ("S101",)),
        ("mypy", ("misc",)),
        ("mypy", ("exclude",)),
        ("mypy", ("ignore_errors",)),
        ("mypy", ("ignore_missing_imports",)),
        ("mypy", ("follow_imports",)),
    }
    assert all(site.path == "pyproject.toml" for site in config_sites(tmp_path))
    line_of_e501 = next(s.line for s in config_sites(tmp_path) if s.codes == ("E501",))
    assert line_of_e501 == 7


def test_ruff_toml_and_mypy_ini_routes(tmp_path: Path) -> None:
    write(tmp_path, "ruff.toml", '[lint]\nignore = ["E501"]\n')
    write(
        tmp_path,
        "mypy.ini",
        "[mypy]\ndisable_error_code = misc, attr-defined\n[mypy-x.*]\nignore_errors = True\n",
    )
    found = {(site.path, site.codes) for site in config_sites(tmp_path)}
    assert found == {
        ("ruff.toml", ("E501",)),
        ("mypy.ini", ("misc",)),
        ("mypy.ini", ("attr-defined",)),
        ("mypy.ini", ("ignore_errors",)),
    }


def test_settings_that_do_not_silence_are_not_routes(tmp_path: Path) -> None:
    write(
        tmp_path,
        "pyproject.toml",
        '[tool.ruff.lint]\nselect = ["E"]\n'
        '[tool.mypy]\nignore_errors = false\nfollow_imports = "normal"\n',
    )
    assert config_sites(tmp_path) == []


def entry(rule: str, path: str) -> RecordEntry:
    return RecordEntry(1, rule, path, REASON, "alice", date(2026, 1, 1), date(2026, 2, 1))


def test_recorded_site_passes_and_unrecorded_fails() -> None:
    found = [Site("a.py", 3, "ruff", ("E501", "F401"))]
    findings = check_suppressions(found, [entry("ruff::E501", "a.py")], full_scan=True)
    assert [f.render() for f in findings] == [
        "a.py:3: pyqaci.suppression.unrecorded ruff::F401 is suppressed here with no exception "
        "in the project record"
    ]


def test_blanket_fails_even_when_something_is_recorded() -> None:
    findings = check_suppressions([Site("a.py", 1, "mypy", ())], [], full_scan=True)
    assert [f.rule for f in findings] == ["pyqaci.suppression.blanket"]


def test_stale_entry_reported_only_on_a_full_scan() -> None:
    record = [entry("ruff::E501", "a.py")]
    stale = check_suppressions([], record, full_scan=True)
    assert [f.rule for f in stale] == ["pyqaci.record.stale"]
    assert check_suppressions([], record, full_scan=False) == []


def test_project_files_outside_git_skip_environments(tmp_path: Path) -> None:
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / "pkg" / "gen").mkdir(parents=True)
    write(tmp_path, ".venv/lib/x.py", "")
    write(tmp_path, "pkg/a.py", "")
    write(tmp_path, "pkg/gen/b.py", "")
    assert project_files(tmp_path, ("pkg/gen/**",)) == ["pkg/a.py"]


def test_project_files_in_git_include_untracked_but_not_ignored(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    write(tmp_path, ".gitignore", "ignored.py\n")
    write(tmp_path, "ignored.py", "")
    write(tmp_path, "kept.py", "")
    write(tmp_path, "stub.pyi", "")
    assert project_files(tmp_path, ()) == ["kept.py", "stub.pyi"]
