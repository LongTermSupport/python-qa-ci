"""What changed against a base ref: the files a diff run (`py-qa run --diff`) is narrowed to.

A change is everything that differs from the merge base of the base and HEAD: the commits on the
branch, staged and unstaged edits, and new files git does not ignore. Measuring from the merge base
means work that reached the base after the branch left it is not counted as this branch's change.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

# Tried in order when [tool.py-qa.diff] base is not set and origin/HEAD names no branch.
_FALLBACK_BASES = ("origin/main", "origin/master", "main", "master")


class DiffError(Exception):
    """What changed cannot be worked out; the message says why."""


@dataclass(frozen=True)
class Change:
    """The files that differ from the merge base, split into present and deleted."""

    base: str
    merge_base: str
    files: tuple[str, ...]
    deleted: tuple[str, ...]


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
        )
    except FileNotFoundError as error:
        msg = "a diff run needs git, and git is not installed"
        raise DiffError(msg) from error


def _exists(root: Path, ref: str) -> bool:
    return _git(root, "rev-parse", "--verify", "--quiet", ref + "^{commit}").returncode == 0


def resolve_base(root: Path, configured: str | None) -> str:
    """Return the base ref: the configured one, origin/HEAD's branch, or the first that exists."""
    if configured is not None:
        return configured
    head = _git(root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if head.returncode == 0 and head.stdout.strip():
        return head.stdout.strip()
    for candidate in _FALLBACK_BASES:
        if _exists(root, candidate):
            return candidate
    msg = (
        "no base to diff against: origin/HEAD is not set and none of "
        f"{', '.join(_FALLBACK_BASES)} exists; name one with --base or [tool.py-qa.diff] base"
    )
    raise DiffError(msg)


def changed_files(root: Path, base: str) -> Change:
    """Return every file that differs from the merge base of base and HEAD, in the work tree."""
    inside = _git(root, "rev-parse", "--is-inside-work-tree")
    if inside.returncode != 0:
        msg = f"a diff run needs a git work tree, and {root} is not in one"
        raise DiffError(msg)
    if not _exists(root, base):
        msg = f"the base {base} is not a commit in this repository"
        raise DiffError(msg)
    merged = _git(root, "merge-base", base, "HEAD")
    if merged.returncode != 0:
        msg = f"{base} and HEAD have no merge base"
        raise DiffError(msg)
    merge_base = merged.stdout.strip()
    status = _git(root, "diff", "--name-status", "-z", "--no-renames", merge_base, "--")
    untracked = _git(root, "ls-files", "-z", "--others", "--exclude-standard")
    for result in (status, untracked):
        if result.returncode != 0:
            msg = f"git could not list the change against {base}: {result.stderr.strip()}"
            raise DiffError(msg)
    fields = [field for field in status.stdout.split("\0") if field]
    present: set[str] = {name for name in untracked.stdout.split("\0") if name}
    deleted: set[str] = set()
    for kind, name in zip(fields[::2], fields[1::2], strict=True):
        (deleted if kind == "D" else present).add(name)
    return Change(base, merge_base, tuple(sorted(present)), tuple(sorted(deleted - present)))
