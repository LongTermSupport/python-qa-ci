"""Path globs for project checks and the diff map, matched against repository-relative paths.

`**` matches any number of directories, `*` and `?` stay within one, and a pattern with no `/`
matches a file name at any depth, as a .gitignore pattern does.
"""

from __future__ import annotations

import functools
import re


@functools.cache
def _compile(pattern: str) -> re.Pattern[str]:
    anchored = "/" in pattern
    parts: list[str] = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            parts.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            parts.append(".*")
            index += 2
        elif pattern[index] == "*":
            parts.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            parts.append("[^/]")
            index += 1
        elif pattern[index] == "[" and (end := pattern.find("]", index + 1)) > index + 1:
            parts.append("[" + pattern[index + 1 : end].replace("\\", "\\\\") + "]")
            index = end + 1
        else:
            parts.append(re.escape(pattern[index]))
            index += 1
    body = "".join(parts)
    return re.compile(body + r"\Z" if anchored else r"(?:.*/)?" + body + r"\Z")


def match_glob(pattern: str, path: str) -> bool:
    """Return True when the repository-relative path matches the glob."""
    return _compile(pattern.lstrip("/")).match(path) is not None


def match_any(patterns: tuple[str, ...], path: str) -> bool:
    """Return True when the path matches any of the globs."""
    return any(match_glob(pattern, path) for pattern in patterns)
