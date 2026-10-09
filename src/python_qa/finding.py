"""A finding reported by one of python-qa's own detectors."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Finding:
    """One finding: where it is, the identifier that resolves to its page, and what is wrong."""

    path: str
    line: int
    rule: str
    message: str

    def render(self) -> str:
        """Return the finding as one line, identifier unaltered, for the command's own output."""
        location = f"{self.path}:{self.line}" if self.line > 0 else self.path
        return f"{location}: {self.rule} {self.message}"
