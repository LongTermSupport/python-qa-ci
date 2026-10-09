"""The Pylint lane reaches every file in the sweep scope, whatever the package layout.

Given a directory, Pylint walks only importable packages, so a file in a directory without an
__init__.py below a package was never analysed and the lane reported clean. These tests run the
real lane on that layout.
"""

import io
from datetime import UTC, datetime
from pathlib import Path

import pytest

from python_qa.config import load_config
from python_qa.pipeline import run_pipeline

BROAD = "import contextlib\n\nwith contextlib.suppress(Exception):\n    pass\n"


def layout(root: Path) -> None:
    (root / "pyproject.toml").write_text("", encoding="utf-8")
    nested = root / "tests" / "unit" / "daemon"
    nested.mkdir(parents=True)
    (root / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (root / "tests" / "unit" / "__init__.py").write_text("", encoding="utf-8")
    (nested / "test_nested.py").write_text(BROAD, encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "clean.py").write_text("X = 1\n", encoding="utf-8")


def pylint_lane(root: Path, paths: tuple[str, ...] | None) -> int:
    return run_pipeline(
        load_config(root),
        requested=("pylint",),
        paths=paths,
        no_fix=True,
        fail_fast=False,
        out=io.StringIO(),
        today=datetime.now(tz=UTC).date(),
    )


@pytest.mark.parametrize("paths", [None, ("tests",), ("tests/unit",)])
def test_file_below_a_non_package_directory_is_analysed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
    paths: tuple[str, ...] | None,
) -> None:
    layout(tmp_path)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    assert pylint_lane(tmp_path, paths) == 1
    assert "tests/unit/daemon/test_nested.py:3:5: W9702" in capfd.readouterr().out


def test_clean_scope_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    layout(tmp_path)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    assert pylint_lane(tmp_path, ("src",)) == 0
