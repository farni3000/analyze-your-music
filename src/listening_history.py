from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from .lastfm import LastFMClient


def normalize_artist_name(value: str) -> str:
    normalized = (value or "").strip().lower()
    normalized = re.sub(r"\(.*?\)", " ", normalized)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _extract_artist_name(track: dict[str, Any]) -> str:
    artist_data = track.get("artist", {})
    if isinstance(artist_data, dict):
        return str(artist_data.get("name", "") or artist_data.get("#text", "")).strip()
    return str(artist_data or "").strip()


def _is_now_playing(track: dict[str, Any]) -> bool:
    if not isinstance(track, dict):
        return False
    return track.get("@attr", {}).get("nowplaying") == "true"


def _build_artist_listen_counts(client: LastFMClient) -> tuple[dict[str, int], int]:
    # Use Last.fm aggregate top artists instead of iterating all historical scrobbles.
    # This is much faster and avoids extremely long first-run backfills.
    counts: dict[str, int] = {}
    total_scrobbles = 0
    for artist_row in client.get_top_artists_overall(limit=1000):
        artist_name = str(artist_row.get("name", "")).strip()
        artist_key = normalize_artist_name(artist_name)
        if not artist_key:
            continue
        try:
            playcount = int(str(artist_row.get("playcount", "0")).strip() or "0")
        except (TypeError, ValueError):
            playcount = 0
        if playcount <= 0:
            continue
        counts[artist_key] = max(counts.get(artist_key, 0), playcount)
        total_scrobbles += playcount
    return counts, total_scrobbles


def _is_stale(last_updated: str, refresh_days: int, now: datetime | None = None) -> bool:
    if not last_updated:
        return True
    now = now or datetime.now(timezone.utc)
    try:
        timestamp = datetime.fromisoformat(last_updated)
    except ValueError:
        return True
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return (now - timestamp) >= timedelta(days=max(refresh_days, 1))


def _load_cached_listening_history(path: str) -> tuple[str, dict[str, int]]:
    if not os.path.exists(path):
        return "", {}
    with open(path, "r", encoding="utf-8") as file:
        payload = json.load(file)
    last_updated = str(payload.get("last_updated", "")).strip()
    raw_counts = payload.get("artist_listen_counts", {})
    if not isinstance(raw_counts, dict):
        return last_updated, {}

    counts: dict[str, int] = {}
    for artist, count in raw_counts.items():
        artist_key = normalize_artist_name(str(artist))
        if not artist_key:
            continue
        try:
            parsed_count = int(count)
        except (TypeError, ValueError):
            continue
        if parsed_count > 0:
            counts[artist_key] = parsed_count
    return last_updated, counts


def _write_cache(path: str, artist_listen_counts: dict[str, int], total_scrobbles: int) -> None:
    output_dir = os.path.dirname(path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    payload = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "total_scrobbles": total_scrobbles,
        "artist_listen_counts": dict(sorted(artist_listen_counts.items())),
    }
    with open(path, "w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2)


def get_artist_listen_counts(
    client: LastFMClient,
    history_path: str,
    refresh_days: int = 30,
) -> tuple[dict[str, int], bool]:
    last_updated, cached_counts = _load_cached_listening_history(history_path)
    if cached_counts and not _is_stale(last_updated, refresh_days):
        return cached_counts, False

    try:
        fresh_counts, total_scrobbles = _build_artist_listen_counts(client)
    except Exception:
        if cached_counts:
            return cached_counts, False
        raise

    _write_cache(history_path, fresh_counts, total_scrobbles)
    return fresh_counts, True


def artist_listen_count(artist_listen_counts: dict[str, int], artist: str) -> int:
    key = normalize_artist_name(artist)
    if not key:
        return 0
    return int(artist_listen_counts.get(key, 0))
