from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.analyzer import WeeklySummary, WeeklyWindow
from src.main import _annotate_rym_highlights
from src.report import _value_with_markers, render_email_html, render_markdown


def _window() -> WeeklyWindow:
    tz = ZoneInfo("UTC")
    return WeeklyWindow(
        start=datetime(2026, 11, 6, 12, 0, tzinfo=tz),
        end=datetime(2026, 11, 13, 12, 0, tzinfo=tz),
    )


def _summary() -> WeeklySummary:
    return WeeklySummary(
        total_scrobbles=10,
        unique_artists=2,
        unique_tracks=3,
        top_albums=[("Album A", 5)],
        top_artists=[("Artist A", 5)],
        top_tracks=[("Track A", 3)],
        day_breakdown=[("Mon", 5)],
    )


@pytest.mark.parametrize(
    ("score", "count", "expected"),
    [
        ("", 0, (False, False, False, False)),
        ("3.59", 999, (False, False, False, False)),
        ("3.6", 1000, (True, False, True, False)),
        ("3.79", 1999, (True, False, True, False)),
        ("3.8", 2000, (True, True, True, True)),
        ("4.12", 25000, (True, True, True, True)),
    ],
)
def test_annotate_rym_highlights_thresholds(score, count, expected):
    rows = [{"rym_score": score, "rym_rating_count": count}]
    _annotate_rym_highlights(rows)
    row = rows[0]
    assert (
        row["highlight_rym_score"],
        row["highlight_rym_score_super"],
        row["highlight_rym_ratings"],
        row["highlight_rym_ratings_super"],
    ) == expected


def test_value_with_markers():
    assert _value_with_markers("3.65", highlight=True) == "3.65 *"
    assert _value_with_markers("3.85", highlight=True, hot=True) == "3.85 **"
    assert _value_with_markers("2.90") == "2.90"
    assert _value_with_markers("") == "n/a"


def test_markdown_marks_rym_levels():
    releases = [
        {"artist": "Super Artist", "album": "Super Album", "rym_score": "3.95", "rym_rating_count": 2500},
        {"artist": "Mid Artist", "album": "Mid Album", "rym_score": "3.62", "rym_rating_count": 1200},
        {"artist": "Low Artist", "album": "Low Album", "rym_score": "2.90", "rym_rating_count": 5},
    ]
    _annotate_rym_highlights(releases)
    content = render_markdown(
        "user",
        _window(),
        _summary(),
        recommendations=[],
        weekly_releases=releases,
    )
    assert "rym: 3.95 ** [2500 **]" in content
    assert "rym: 3.62 * [1200 *]" in content
    assert "rym: 2.90 [5]" in content


def test_html_marks_rym_levels():
    releases = [
        {"artist": "Super Artist", "album": "Super Album", "rym_score": "3.95", "rym_rating_count": 2500},
        {"artist": "Mid Artist", "album": "Mid Album", "rym_score": "3.62", "rym_rating_count": 1200},
    ]
    _annotate_rym_highlights(releases)
    content = render_email_html("user", _window(), _summary(), [], releases)
    assert "<td><span class='metric-pill metric-hit score-hot'>3.95</span></td>" in content
    assert "<td><span class='metric-pill metric-hit score-hot'>2500</span></td>" in content
    assert "<td><span class='metric-pill metric-hit'>3.62</span></td>" in content
    assert "<td><span class='metric-pill metric-hit'>1200</span></td>" in content
