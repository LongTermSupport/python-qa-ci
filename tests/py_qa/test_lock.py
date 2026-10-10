"""Tests for the run lock: one py-qa run at a time in a work tree."""

import os
import subprocess
from pathlib import Path

import pytest

from py_qa.config import load_config
from py_qa.lock import LockHeldError, lock_path, run_lock


def test_the_lock_lives_in_the_git_directory_by_default(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    path = lock_path(load_config(tmp_path))
    assert path == tmp_path / ".git" / "py-qa" / "run.lock"


def test_outside_git_there_is_no_default_lock(tmp_path: Path) -> None:
    assert lock_path(load_config(tmp_path)) is None


def test_a_configured_lock_path_and_a_lock_switched_off(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.py-qa]\nlock = "run/qa.lock"\n', "utf-8")
    assert lock_path(load_config(tmp_path)) == tmp_path / "run" / "qa.lock"
    (tmp_path / "pyproject.toml").write_text("[tool.py-qa]\nlock = false\n", "utf-8")
    assert lock_path(load_config(tmp_path)) is None


def test_a_second_run_is_refused_while_the_first_holds_the_lock(tmp_path: Path) -> None:
    path = tmp_path / "run" / "qa.lock"
    with run_lock(path):
        assert path.read_text(encoding="utf-8") == f"pid={os.getpid()}\n"
        with pytest.raises(LockHeldError, match=f"pid={os.getpid()}"), run_lock(path):
            pass
    with run_lock(path):
        pass


def test_no_path_is_no_lock() -> None:
    with run_lock(None):
        pass
