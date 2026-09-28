from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .lastfm import LastFMClient


@dataclass
class WeeklyWindow:
    start: datetime
    end: datetime


@dataclass
class WeeklySummary:
    total_scrobbles: int
    unique_artists: int
    unique_tracks: int
    top_albums: list[tuple[str, int]]
    top_artists: list[tuple[str, int]]
    top_tracks: list[tuple[str, int]]
    day_breakdown: list[tuple[str, int]]


def current_week_window(tz_name: str) -> WeeklyWindow:
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    start = now - timedelta(days=7)
    return WeeklyWindow(start=start, end=now)


def summarize_week(client: LastFMClient, window: WeeklyWindow) -> tuple[WeeklySummary, list[dict]]:
    from_ts = int(window.start.timestamp())
    to_ts = int(window.end.timestamp())
    tracks = [
        t for t in client.get_recent_tracks(from_ts=from_ts, to_ts=to_ts)
        if "@attr" not in t or t.get("@attr", {}).get("nowplaying") != "true"
    ]

    artist_counter: Counter[str] = Counter()
    track_counter: Counter[str] = Counter()
    album_counter: Counter[str] = Counter()
    day_counter: Counter[str] = Counter()

    for t in tracks:
        artist = (t.get("artist", {}) or {}).get("name", "").strip()
        name = t.get("name", "").strip()
        album = (t.get("album", {}) or {}).get("#text", "").strip()
        date_uts = ((t.get("date", {}) or {}).get("uts", "")).strip()
        if artist:
            artist_counter[artist] += 1
        if artist and name:
            track_counter[f"{artist} - {name}"] += 1
        if artist and album:
            album_counter[f"{artist} - {album}"] += 1
        if date_uts:
            dt = datetime.fromtimestamp(int(date_uts), tz=window.start.tzinfo)
            day_counter[dt.strftime("%Y-%m-%d")] += 1

    # Show real calendar days touched by the exact 7-day window, newest first.
    # This avoids weekday double-counting (e.g. two Saturdays in one rolling window).
    end_date = window.end.date()
    start_date = window.start.date()
    day_breakdown: list[tuple[str, int]] = []
    current_date = end_date
    while current_date >= start_date:
        key = current_date.strftime("%Y-%m-%d")
        label = f"{current_date.strftime('%A')} ({current_date.strftime('%d.%m.%Y')})"
        day_breakdown.append((label, int(day_counter.get(key, 0))))
        current_date = current_date - timedelta(days=1)

    summary = WeeklySummary(
        total_scrobbles=len(tracks),
        unique_artists=len(artist_counter),
        unique_tracks=len(track_counter),
        top_albums=album_counter.most_common(10),
        top_artists=artist_counter.most_common(10),
        top_tracks=track_counter.most_common(10),
        day_breakdown=day_breakdown,
    )
    return summary, tracks
