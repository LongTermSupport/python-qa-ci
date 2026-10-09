"""Tests for the finding line format."""

from python_qa.finding import Finding


def test_render_prints_location_identifier_and_message() -> None:
    finding = Finding("src/a.py", 3, "pyqaci.suppression.unrecorded", "no record entry")
    assert finding.render() == "src/a.py:3: pyqaci.suppression.unrecorded no record entry"


def test_render_omits_line_when_finding_is_about_the_whole_file() -> None:
    finding = Finding("qa/record.toml", 0, "pyqaci.record.invalid", "bad")
    assert finding.render() == "qa/record.toml: pyqaci.record.invalid bad"


def test_findings_sort_by_path_then_line() -> None:
    later = Finding("b.py", 1, "x", "m")
    earlier = Finding("a.py", 9, "x", "m")
    assert sorted([later, earlier]) == [earlier, later]
