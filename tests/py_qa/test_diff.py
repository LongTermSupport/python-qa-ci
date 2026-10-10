"""Tests for finding what changed against a base: committed, staged, unstaged and new files."""

import subprocess
from pathlib import Path

import pytest

from py_qa.diff import DiffError, changed_files, resolve_base


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout


def repo(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "dev@example.com")
    git(tmp_path, "config", "user.name", "Dev")
    git(tmp_path, "config", "commit.gpgsign", "false")
    for name in ("keep.py", "gone.py", "edited.py", "staged.py"):
        (tmp_path / name).write_text("x = 1\n", encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "base")
    git(tmp_path, "checkout", "-q", "-b", "work")
    return tmp_path


def test_every_kind_of_change_is_found(tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / "committed.py").write_text("y = 2\n", encoding="utf-8")
    git(root, "add", "committed.py")
    git(root, "commit", "-q", "-m", "work")
    (root / "gone.py").unlink()
    (root / "edited.py").write_text("x = 2\n", encoding="utf-8")
    (root / "staged.py").write_text("x = 3\n", encoding="utf-8")
    git(root, "add", "staged.py")
    (root / "new.py").write_text("z = 1\n", encoding="utf-8")
    change = changed_files(root, "main")
    assert change.files == ("committed.py", "edited.py", "new.py", "staged.py")
    assert change.deleted == ("gone.py",)
    assert change.base == "main"
    assert len(change.merge_base) == 40


def test_a_rename_is_a_deletion_and_an_addition(tmp_path: Path) -> None:
    root = repo(tmp_path)
    git(root, "mv", "keep.py", "kept.py")
    change = changed_files(root, "main")
    assert change.files == ("kept.py",)
    assert change.deleted == ("keep.py",)


def test_the_base_branch_moving_on_is_not_a_change(tmp_path: Path) -> None:
    root = repo(tmp_path)
    git(root, "checkout", "-q", "main")
    (root / "later.py").write_text("x = 1\n", encoding="utf-8")
    git(root, "add", "later.py")
    git(root, "commit", "-q", "-m", "main moves")
    git(root, "checkout", "-q", "work")
    assert changed_files(root, "main").files == ()


def test_an_unknown_base_is_an_error(tmp_path: Path) -> None:
    root = repo(tmp_path)
    with pytest.raises(DiffError, match="nope"):
        changed_files(root, "nope")


def test_resolve_base_prefers_the_configured_ref(tmp_path: Path) -> None:
    root = repo(tmp_path)
    assert resolve_base(root, "work") == "work"


def test_resolve_base_falls_back_to_a_local_main(tmp_path: Path) -> None:
    assert resolve_base(repo(tmp_path), None) == "main"


def test_resolve_base_follows_origin_head(tmp_path: Path) -> None:
    upstream = repo(tmp_path / "upstream")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(upstream), str(clone)], check=True)
    assert resolve_base(clone, None) == "origin/work"


def test_resolve_base_without_any_candidate_is_an_error(tmp_path: Path) -> None:
    root = repo(tmp_path)
    git(root, "branch", "-q", "-m", "main", "trunk")
    with pytest.raises(DiffError, match=r"\[tool.py-qa.diff\] base"):
        resolve_base(root, None)


def test_outside_git_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(DiffError, match="git"):
        changed_files(tmp_path, "main")
