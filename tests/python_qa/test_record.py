"""Tests for loading and checking the project record."""

from datetime import date
from pathlib import Path

import pytest

from python_qa.config import RecordPolicy
from python_qa.record import RecordEntry, check_record, is_generic, load_record

GOOD = (
    "The subprocess call runs a fixed argument list built from constants in this module, "
    "so no caller-supplied text reaches the shell."
)
TODAY = date(2026, 3, 1)


def entry_text(**overrides: str) -> str:
    fields = {
        "rule": '"ruff::S603"',
        "path": '"src/run.py"',
        "justification": f'"{GOOD}"',
        "decided_by": '"alice"',
        "decided_on": "2026-01-15",
        "review_by": "2026-04-15",
    }
    fields.update(overrides)
    body = "\n".join(f"{key} = {value}" for key, value in fields.items() if value != "")
    return f"[[exception]]\n{body}\n"


def load(tmp_path: Path, text: str) -> tuple[list[RecordEntry], list[str]]:
    path = tmp_path / "record.toml"
    path.write_text(text, encoding="utf-8")
    entries, findings = load_record(path, "qa/record.toml", today=TODAY)
    return entries, [finding.render() for finding in findings]


def test_missing_record_is_empty(tmp_path: Path) -> None:
    entries, findings = load_record(tmp_path / "none.toml", "qa/record.toml", today=TODAY)
    assert entries == []
    assert findings == []


def test_valid_entry_loads(tmp_path: Path) -> None:
    entries, findings = load(tmp_path, entry_text())
    assert findings == []
    assert entries == [
        RecordEntry(1, "ruff::S603", "src/run.py", GOOD, "alice", date(2026, 1, 15), date(2026, 4, 15))
    ]


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"rule": '"S603"'}, "rule must be"),
        ({"rule": '"flake::S603"'}, "rule must be"),
        ({"path": '"src/*.py"'}, "one file"),
        ({"path": '"/abs/run.py"'}, "relative"),
        ({"path": '"../run.py"'}, "relative"),
        ({"justification": '"legacy"'}, "generic"),
        ({"justification": '"TODO: needed for now, will fix later, known issue"'}, "generic"),
        ({"justification": ""}, "justification is missing"),
        ({"decided_by": '"ci-bot"'}, "automation"),
        ({"decided_by": '""'}, "decided_by is missing"),
        ({"decided_on": '"yesterday"'}, "must be a date"),
        ({"review_by": "2026-01-10"}, "after decided_on"),
        ({"review_by": "2027-06-01"}, "180 days"),
        ({"decided_on": "2026-05-01", "review_by": "2026-06-01"}, "in the future"),
        ({"extra": "1"}, "unknown key"),
    ],
)
def test_invalid_entries_are_reported_and_dropped(
    tmp_path: Path, overrides: dict[str, str], fragment: str
) -> None:
    entries, findings = load(tmp_path, entry_text(**overrides))
    assert entries == []
    assert len(findings) == 1
    assert "pyqaci.record.invalid" in findings[0]
    assert fragment in findings[0]


def test_unparseable_record(tmp_path: Path) -> None:
    entries, findings = load(tmp_path, "[[exception]\n")
    assert entries == []
    assert "cannot parse" in findings[0]


def test_unknown_top_level_table(tmp_path: Path) -> None:
    _, findings = load(tmp_path, "[other]\nx = 1\n")
    assert "unknown key other" in findings[0]


def test_pasted_justification_is_rejected(tmp_path: Path) -> None:
    text = entry_text() + entry_text(path='"src/other.py"')
    entries, findings = load(tmp_path, text)
    assert len(entries) == 1
    assert "same justification as exception #1" in findings[0]


def test_generic_check() -> None:
    assert is_generic("legacy")
    assert is_generic("Needed for now - TODO fix later")
    assert not is_generic(GOOD)


def make(rule: str, path: str, review_by: date = date(2026, 4, 15)) -> RecordEntry:
    return RecordEntry(1, rule, path, GOOD, "alice", date(2026, 1, 15), review_by)


def test_budget_total_and_per_rule() -> None:
    entries = [make("ruff::S603", f"src/{n}.py") for n in range(3)]
    policy = RecordPolicy(max_total=2, max_per_rule=1)
    rendered = [finding.render() for finding in check_record(entries, policy, "qa/record.toml", TODAY)]
    assert any("pyqaci.record.budget" in line and "3 exceptions" in line for line in rendered)
    assert any("ruff::S603" in line and "max_per_rule" in line for line in rendered)


def test_expired_entry() -> None:
    entries = [make("ruff::S603", "src/a.py", review_by=date(2026, 2, 1))]
    findings = check_record(entries, RecordPolicy(), "qa/record.toml", TODAY)
    assert [finding.rule for finding in findings] == ["pyqaci.record.expired"]


def test_within_budget_and_in_date_is_clean() -> None:
    assert check_record([make("ruff::S603", "src/a.py")], RecordPolicy(), "r", TODAY) == []
