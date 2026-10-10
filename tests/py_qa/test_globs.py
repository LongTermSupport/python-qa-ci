"""Tests for the path globs project checks and the diff map are written in."""

import pytest

from py_qa.globs import match_any, match_glob


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("docs/**/*.md", "docs/a.md", True),
        ("docs/**/*.md", "docs/x/y/a.md", True),
        ("docs/**/*.md", "docsx/a.md", False),
        ("docs/*.md", "docs/x/a.md", False),
        ("*.md", "README.md", True),
        ("*.md", "docs/deep/README.md", True),
        ("conftest.py", "tests/unit/conftest.py", True),
        ("src/**", "src/pkg/a.py", True),
        ("src/**", "src", False),
        ("scripts/qa/*.py", "scripts/qa/check.py", True),
        ("scripts/qa/*.py", "scripts/qa/lib/check.py", False),
        ("requirements*.txt", "requirements-dev.txt", True),
        ("a?c.py", "abc.py", True),
        ("a?c.py", "a/c.py", False),
        ("**/*.sh", "run.sh", True),
        ("tests/[ab].py", "tests/a.py", True),
    ],
)
def test_match_glob(pattern: str, path: str, expected: bool) -> None:
    assert match_glob(pattern, path) is expected


def test_match_any() -> None:
    assert match_any(("*.toml", "src/**"), "src/a.py")
    assert not match_any((), "src/a.py")
