"""The project record: every exception a project has decided to keep, with its reason."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

import tomllib

from python_qa.config import RecordPolicy
from python_qa.finding import Finding

INVALID = "pyqaci.record.invalid"
BUDGET = "pyqaci.record.budget"
EXPIRED = "pyqaci.record.expired"
STALE = "pyqaci.record.stale"

TOOL_PREFIXES = ("ruff", "pylint", "mypy", "pyright", "bandit", "semgrep")
_RULE = re.compile(r"^(?:" + "|".join(TOOL_PREFIXES) + r")::[A-Za-z0-9_.\-]+$")
_FIELDS = ("rule", "path", "justification", "decided_by", "decided_on", "review_by")
_MIN_CHARACTERS = 40
_MIN_OWN_WORDS = 6
# Stock phrases that fit any exception unchanged. They are removed before the remaining words
# are counted, so a justification made only of them, or padded with them, is rejected.
GENERIC_PHRASES = (
    "needed for now",
    "for now",
    "will fix later",
    "fix later",
    "known issue",
    "technical debt",
    "tech debt",
    "false positive",
    "not applicable",
    "same as above",
    "as above",
    "see above",
    "by design",
    "no reason",
    "won't fix",
    "wontfix",
    "legacy code",
    "legacy",
    "todo",
    "fixme",
    "temporary",
    "workaround",
    "intentional",
    "required",
    "necessary",
    "ignore",
    "ignored",
    "suppress",
    "suppressed",
    "n/a",
)
_AUTOMATION = re.compile(
    r"(?:^|[-_.\s])(?:bot|ci|agent|automation|claude|gpt|gemini|copilot|model)(?:$|[-_.\s\[])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RecordEntry:
    """One exception: the identifier, the one file it covers, and who decided it, when and why."""

    number: int
    rule: str
    path: str
    justification: str
    decided_by: str
    decided_on: date
    review_by: date


def is_generic(justification: str) -> bool:
    """Return True when the justification has too few words of its own to name hazard and scope.

    The check removes every stock phrase in GENERIC_PHRASES, then requires at least six words to
    remain. It cannot tell whether the sentence is true; that is the reviewer's judgement.
    """
    text = justification.lower()
    for phrase in sorted(GENERIC_PHRASES, key=len, reverse=True):
        text = re.sub(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", " ", text)
    words = re.findall(r"[a-z0-9][a-z0-9'_-]*", text)
    return len(words) < _MIN_OWN_WORDS


def load_record(
    path: Path, display: str, *, today: date, max_review_days: int = 180
) -> tuple[list[RecordEntry], list[Finding]]:
    """Read the record at path; invalid entries are reported and left out of the result."""
    if not path.is_file():
        return [], []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        return [], [Finding(display, 0, INVALID, f"cannot parse: {error}")]
    findings = [
        Finding(display, 0, INVALID, f"unknown key {key}; the record holds [[exception]] only")
        for key in sorted(set(data) - {"exception"})
    ]
    raw_entries = data.get("exception", [])
    if not isinstance(raw_entries, list):
        return [], [*findings, Finding(display, 0, INVALID, "exception must be [[exception]]")]
    entries: list[RecordEntry] = []
    seen: dict[str, int] = {}
    for number, raw in enumerate(raw_entries, start=1):
        problems = _problems(raw, today, max_review_days)
        if not problems:
            justification = str(raw["justification"]).strip()
            first = seen.setdefault(justification.lower(), number)
            if first != number:
                problems = [f"has the same justification as exception #{first}; say why this one"]
        label = _label(number, raw)
        if problems:
            findings.extend(Finding(display, 0, INVALID, f"{label}: {p}") for p in problems)
            continue
        entries.append(
            RecordEntry(
                number,
                raw["rule"],
                raw["path"],
                str(raw["justification"]).strip(),
                str(raw["decided_by"]).strip(),
                raw["decided_on"],
                raw["review_by"],
            )
        )
    return entries, findings


def check_record(
    entries: list[RecordEntry], policy: RecordPolicy, display: str, today: date
) -> list[Finding]:
    """Return budget and expiry findings for valid entries."""
    findings: list[Finding] = []
    if len(entries) > policy.max_total:
        findings.append(
            Finding(
                display,
                0,
                BUDGET,
                f"{len(entries)} exceptions, over max_total = {policy.max_total}; "
                "fix instances and remove entries, or have the Owner raise the budget",
            )
        )
    for rule, count in sorted(Counter(entry.rule for entry in entries).items()):
        if count > policy.max_per_rule:
            findings.append(
                Finding(
                    display,
                    0,
                    BUDGET,
                    f"{count} exceptions for {rule}, over max_per_rule = {policy.max_per_rule}; "
                    "a rule excepted this often is a calibration for the Owner to decide",
                )
            )
    findings.extend(
        Finding(
            display,
            0,
            EXPIRED,
            f"exception #{entry.number} ({entry.rule}, {entry.path}): review_by "
            f"{entry.review_by.isoformat()} has passed; re-decide it or remove it",
        )
        for entry in entries
        if entry.review_by < today
    )
    return findings


def _label(number: int, raw: object) -> str:
    if isinstance(raw, dict) and isinstance(raw.get("rule"), str):
        return f"exception #{number} ({raw['rule']}, {raw.get('path', '?')})"
    return f"exception #{number}"


def _problems(raw: object, today: date, max_review_days: int) -> list[str]:
    if not isinstance(raw, dict):
        return ["must be a table"]
    problems = [f"unknown key {key}" for key in sorted(set(raw) - set(_FIELDS))]
    problems.extend(f"{key} is missing" for key in _FIELDS if not _present(raw.get(key)))
    if problems:
        return problems
    problems.extend(_rule_and_path(raw))
    problems.extend(_people_and_reason(raw))
    problems.extend(_dates(raw["decided_on"], raw["review_by"], today, max_review_days))
    return problems


def _present(value: Any) -> bool:
    return value is not None and not (isinstance(value, str) and not value.strip())


def _rule_and_path(raw: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    rule, path = raw["rule"], raw["path"]
    if not isinstance(rule, str) or not _RULE.match(rule):
        problems.append(
            "rule must be <tool>::<identifier as printed>, tool one of " + ", ".join(TOOL_PREFIXES)
        )
    if not isinstance(path, str):
        problems.append("path must be a string")
    elif any(char in path for char in "*?["):
        problems.append("path must name one file; a glob is not an exception, it is a policy")
    elif PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts:
        problems.append("path must be relative to the project root, without ..")
    return problems


def _people_and_reason(raw: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    justification, decided_by = raw["justification"], raw["decided_by"]
    if not isinstance(justification, str):
        problems.append("justification must be a string")
    elif len(justification.strip()) < _MIN_CHARACTERS or is_generic(justification):
        problems.append(
            "justification is generic or too short; name the hazard accepted and the scope, "
            f"in at least {_MIN_OWN_WORDS} words of its own"
        )
    if not isinstance(decided_by, str):
        problems.append("decided_by must be a string")
    elif _AUTOMATION.search(decided_by):
        problems.append("decided_by names automation; an exception is decided by a person")
    return problems


def _dates(decided_on: object, review_by: object, today: date, max_review_days: int) -> list[str]:
    if not isinstance(decided_on, date) or not isinstance(review_by, date):
        return ["decided_on and review_by must be a date (YYYY-MM-DD, unquoted)"]
    if decided_on > today:
        return [f"decided_on {decided_on.isoformat()} is in the future"]
    if review_by <= decided_on:
        return ["review_by must be after decided_on"]
    if (review_by - decided_on).days > max_review_days:
        return [f"review_by is more than {max_review_days} days after decided_on"]
    return []
