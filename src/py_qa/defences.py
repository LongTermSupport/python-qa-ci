"""Every defence active in a project, derived from the configuration in force, run by none."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from py_qa.tools import mypy_enabled_codes, pylint_messages, ruff_enabled_rules

if TYPE_CHECKING:
    from py_qa.config import Config

# py-qa's own detectors and lane failures: identifier -> (lane that reports it, summary).
BUILTIN = {
    "pyqaci.format": ("fmt", "Code is formatted by ruff format."),
    "pyqaci.record.invalid": (
        "record",
        "Every record exception names one file, a person, dates and a specific justification.",
    ),
    "pyqaci.record.budget": ("record", "The record stays within its total and per-rule budget."),
    "pyqaci.record.expired": ("record", "No record exception is past its review_by date."),
    "pyqaci.record.stale": ("suppression", "Every record exception covers a suppression."),
    "pyqaci.suppression.unrecorded": (
        "suppression",
        "Every suppression comment or setting has a matching record exception.",
    ),
    "pyqaci.suppression.blanket": (
        "suppression",
        "No suppression silences a tool without naming the identifier.",
    ),
    "pyqaci.suppression.unscanned": (
        "suppression",
        "Every Python file can be read, so its suppressions can be checked.",
    ),
    "pyqaci.summary.stale": ("summary", "The generated agent summary matches the configuration."),
    "pyqaci.docs.dangling": ("docs", "Every listed identifier resolves to documentation."),
    "pyqaci.tests": ("test", "The test suite passes."),
    "pyqaci.coverage": ("coverage", "Line coverage stays at or above coverage.fail_under."),
    "pyqaci.audit": ("audit", "No installed dependency has a known vulnerability."),
}


@dataclass(frozen=True)
class Defence:
    """One active defence: the identifier it prints, who supplies it, and what it requires."""

    identifier: str
    tool: str
    origin: str
    summary: str

    @property
    def doc(self) -> str:
        """Return the command that prints this defence's documentation, offline."""
        return f"py-qa rule-doc {self.identifier}"


def active_defences(config: Config) -> list[Defence]:
    """Return every defence the configuration switches on, without running any of them."""
    defences = [
        Defence(identifier, "py-qa", "bundled", summary)
        for identifier, (lane, summary) in BUILTIN.items()
        if config.tools[lane]
        and (lane != "summary" or config.summary_file)
        and (lane != "coverage" or (config.tools["test"] and not config.test_command))
    ]
    if config.tools["pylint"]:
        defences.extend(
            Defence(message.symbol, "pylint", message.origin, message.summary)
            for message in pylint_messages(config)
        )
    if config.tools["ruff"]:
        defences.extend(
            Defence(code, "ruff", "ruff", name) for code, name in ruff_enabled_rules(config.root)
        )
    if config.tools["mypy"]:
        defences.extend(
            Defence(code, "mypy", "mypy", description)
            for code, description in mypy_enabled_codes(config.root)
        )
    return defences
