"""Tests for choosing the tests a change can affect, from the project's import and path graph."""

import json
import subprocess
from pathlib import Path

import pytest

from py_qa import __version__, affected
from py_qa.affected import Selection, _cached_scan, scan_source, select_tests
from py_qa.config import load_config
from py_qa.diff import Change


def write(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def project(tmp_path: Path, pyproject: str = "") -> Path:
    write(
        tmp_path,
        {
            "pyproject.toml": pyproject,
            "src/pkg/__init__.py": "",
            "src/pkg/a.py": "VALUE = 1\n",
            "src/pkg/b.py": "from pkg.a import VALUE\n",
            "src/pkg/c.py": "from . import a\n",
            "src/pkg/other.py": "OTHER = 2\n",
            "src/pkg/lonely.py": "ALONE = 3\n",
            "src/pkg/sub/__init__.py": "from ..a import VALUE\n",
            "src/pkg/sub/deep.py": "X = 1\n",
            "scripts/run.sh": "echo hi\n",
            "scripts/check_thing.py": "print('thing')\n",
            "docs/guide.md": "# Guide\n",
            "data/table.csv": "a,b\n",
            "tests/conftest.py": "",
            "tests/helpers.py": "import pkg.other\n",
            "tests/test_b.py": "import pkg.b\n",
            "tests/test_c.py": "from pkg import c\n",
            "tests/test_other.py": "from helpers import *\n",
            "tests/test_patch.py": "PATCH = 'pkg.a.VALUE'\n",
            "tests/test_script.py": "SCRIPT = 'scripts/run.sh'\nNAME = 'check_thing.py'\n",
            "tests/test_deep.py": "import pkg.sub.deep\n",
            "tests/unit/conftest.py": "",
            "tests/unit/test_unit.py": "",
        },
    )
    return tmp_path


def select(root: Path, *files: str, deleted: tuple[str, ...] = ()) -> Selection:
    return select_tests(load_config(root), Change("main", "0" * 40, tuple(files), deleted))


def test_a_module_selects_the_tests_that_import_it_directly_or_through_others(
    tmp_path: Path,
) -> None:
    selection = select(project(tmp_path), "src/pkg/a.py")
    assert not selection.full
    assert selection.tests == ("tests/test_b.py", "tests/test_c.py", "tests/test_patch.py")
    assert selection.reached_by["tests/test_b.py"] == ("src/pkg/a.py",)
    assert selection.unmapped == ()
    assert selection.untested == ()


def test_a_package_init_reaches_every_importer_of_the_package(tmp_path: Path) -> None:
    selection = select(project(tmp_path), "src/pkg/sub/__init__.py")
    assert selection.tests == ("tests/test_deep.py",)


def test_what_an_init_or_a_conftest_imports_reaches_only_those_naming_it(tmp_path: Path) -> None:
    root = project(tmp_path)
    write(root, {"tests/unit/conftest.py": "import pkg.lonely\n"})
    selection = select(root, "src/pkg/lonely.py")
    assert selection.tests == ()
    assert selection.untested == ("src/pkg/lonely.py",)


def test_a_test_helper_reaches_the_tests_that_import_it(tmp_path: Path) -> None:
    selection = select(project(tmp_path), "src/pkg/other.py")
    assert selection.tests == ("tests/test_other.py",)


def test_a_changed_test_selects_itself(tmp_path: Path) -> None:
    assert select(project(tmp_path), "tests/test_b.py").tests == ("tests/test_b.py",)


def test_a_conftest_selects_the_tests_below_it(tmp_path: Path) -> None:
    assert select(project(tmp_path), "tests/unit/conftest.py").tests == ("tests/unit/test_unit.py",)


def test_files_named_by_path_or_unique_name_select_the_tests_that_name_them(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)
    assert select(root, "scripts/run.sh").tests == ("tests/test_script.py",)
    assert select(root, "scripts/check_thing.py").tests == ("tests/test_script.py",)


def test_an_unmapped_file_is_reported_and_runs_everything_by_default(tmp_path: Path) -> None:
    selection = select(project(tmp_path), "docs/guide.md")
    assert selection.unmapped == ("docs/guide.md",)
    assert selection.full
    assert selection.full_reasons == ("docs/guide.md: no test is known to read it",)


def test_an_unmapped_file_can_be_ignored(tmp_path: Path) -> None:
    root = project(tmp_path, '[tool.py-qa.diff]\nunmapped = "ignore"\n')
    selection = select(root, "docs/guide.md")
    assert selection.unmapped == ("docs/guide.md",)
    assert not selection.full
    assert selection.tests == ()


def test_the_map_covers_files_the_graph_cannot_reach(tmp_path: Path) -> None:
    root = project(
        tmp_path,
        '[[tool.py-qa.diff.map]]\nglob = "docs/**/*.md"\ntests = ["tests/test_b.py"]\n'
        '[[tool.py-qa.diff.map]]\nglob = "*.csv"\ntests = []\n',
    )
    selection = select(root, "docs/guide.md", "data/table.csv")
    assert not selection.full
    assert selection.tests == ("tests/test_b.py",)
    assert selection.unmapped == ()


def test_a_map_entry_can_exclude_files_its_glob_matches(tmp_path: Path) -> None:
    root = project(
        tmp_path,
        '[[tool.py-qa.diff.map]]\nglob = "docs/**/*.md"\nexclude = ["docs/guide.md"]\n'
        'tests = ["tests/test_b.py"]\n',
    )
    selection = select(root, "docs/guide.md")
    assert selection.tests == ()
    assert selection.unmapped == ("docs/guide.md",)


def test_a_map_naming_a_missing_test_is_reported(tmp_path: Path) -> None:
    root = project(tmp_path, '[[tool.py-qa.diff.map]]\nglob = "*.md"\ntests = ["tests/gone.py"]\n')
    assert select(root, "docs/guide.md").missing == ("tests/gone.py",)


def test_full_tests_on_runs_everything(tmp_path: Path) -> None:
    selection = select(project(tmp_path), "pyproject.toml", "src/pkg/a.py")
    assert selection.full
    assert selection.full_reasons == ("pyproject.toml: listed in [tool.py-qa.diff] full_tests_on",)


def test_a_deleted_module_selects_the_tests_that_still_import_it(tmp_path: Path) -> None:
    root = project(tmp_path)
    (root / "src/pkg/b.py").unlink()
    assert select(root, deleted=("src/pkg/b.py",)).tests == ("tests/test_b.py",)


def test_a_module_no_test_reaches_is_reported_as_untested(tmp_path: Path) -> None:
    selection = select(project(tmp_path), "src/pkg/lonely.py")
    assert selection.tests == ()
    assert selection.untested == ("src/pkg/lonely.py",)


def test_pytest_python_files_and_testpaths_decide_what_a_test_is(tmp_path: Path) -> None:
    root = project(
        tmp_path,
        '[tool.pytest.ini_options]\npython_files = "check_*.py"\ntestpaths = ["scripts"]\n',
    )
    write(root, {"tests/test_x.py": "import pkg.a\n", "scripts/check_a.py": "import pkg.a\n"})
    assert select(root, "src/pkg/a.py").tests == ("scripts/check_a.py",)


def test_unparsable_python_is_skipped_not_fatal(tmp_path: Path) -> None:
    root = project(tmp_path)
    write(root, {"tests/test_broken.py": "def (:\n"})
    selection = select(root, "tests/test_broken.py")
    assert selection.tests == ("tests/test_broken.py",)


def git_project(tmp_path: Path) -> Path:
    root = project(tmp_path)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def test_scans_are_cached_and_a_changed_file_is_read_again(tmp_path: Path) -> None:
    root = git_project(tmp_path)
    cache = root / ".git" / "py-qa" / "affected-cache.json"
    assert select(root, "src/pkg/b.py").tests == ("tests/test_b.py",)
    assert cache.is_file()
    stored = json.loads(cache.read_text(encoding="utf-8"))
    assert "tests/test_b.py" in stored["files"]
    assert select(root, "src/pkg/b.py").tests == ("tests/test_b.py",)
    write(root, {"tests/test_b.py": "import pkg.other  # now tests something else\n"})
    assert select(root, "src/pkg/b.py").tests == ()


def test_a_damaged_cache_is_read_as_empty(tmp_path: Path) -> None:
    root = git_project(tmp_path)
    cache = root / ".git" / "py-qa" / "affected-cache.json"
    cache.parent.mkdir(parents=True)
    for damaged in (
        "not json",
        '{"version": "0"}',
        json.dumps({"version": __version__, "files": 3}),
    ):
        cache.write_text(damaged, encoding="utf-8")
        assert select(root, "src/pkg/b.py").tests == ("tests/test_b.py",)
    entry = {"tests/test_b.py": [[0, 0], [["x", 0]], []]}
    cache.write_text(json.dumps({"version": __version__, "files": entry}), encoding="utf-8")
    assert select(root, "src/pkg/b.py").tests == ("tests/test_b.py",)


@pytest.mark.parametrize(
    "entry",
    [
        [[1, 2], [], []],
        [[3, 4], "imports", []],
        [[3, 4], [["pkg", 0]], []],
        [[3, 4], [["pkg", "0", []]], []],
        "entry",
    ],
)
def test_a_stale_or_malformed_cache_entry_is_parsed_again(entry: object) -> None:
    assert _cached_scan(entry, [3, 4]) is None


def test_a_cache_entry_is_read_back() -> None:
    entry = [[3, 4], [["pkg", 1, ["x"]]], ["pkg.mod"]]
    assert _cached_scan(entry, [3, 4]) == ([("pkg", 1, ("x",))], ["pkg.mod"])


def test_many_files_are_parsed_in_parallel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(affected, "PARALLEL_THRESHOLD", 1)
    assert select(project(tmp_path), "src/pkg/b.py").tests == ("tests/test_b.py",)


def test_scan_source_reads_imports_and_name_like_strings() -> None:
    imports, strings = scan_source(
        "import a.b\nfrom . import c\nfrom .d import *\nX = 'pkg.mod'\nY = 'plain'\nZ = 'a/b.sh'\n"
    )
    assert imports == [("a.b", 0, ()), ("", 1, ("c",)), ("d", 1, ())]
    assert strings == ["pkg.mod", "a/b.sh"]
    assert scan_source("def (:\n") == ([], [])
