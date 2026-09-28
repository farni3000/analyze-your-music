from __future__ import annotations

import difflib
import random
from collections import Counter, defaultdict
from typing import Any

from .lastfm import LastFMClient
from .llm import recommend_albums_with_llm


KNOWN_ALBUM_PLAYS_THRESHOLD = 20


def build_known_history(client: LastFMClient) -> tuple[dict[str, int], dict[str, int]]:
    album_playcounts: dict[str, int] = {}
    for album in client.get_top_albums_overall(limit=1000):
        artist = (album.get("artist", {}) or {}).get("name", "").strip()
        name = album.get("name", "").strip()
        playcount = int(str(album.get("playcount", "0")).strip() or "0")
        if artist and name:
            album_playcounts[f"{artist} - {name}".lower()] = playcount

    artist_playcounts: dict[str, int] = {}
    for artist in client.get_top_artists_overall(limit=1000):
        name = artist.get("name", "").strip()
        playcount = int(str(artist.get("playcount", "0")).strip() or "0")
        if name:
            artist_playcounts[name.lower()] = playcount
    return album_playcounts, artist_playcounts


def _heuristic_score(similarity_score: float, artist_history: int, album_history: int) -> float:
    novelty_boost = (1 / (1 + artist_history)) + (2 / (1 + album_history))
    return similarity_score * 10 + novelty_boost * 5


def _sample_history(client: LastFMClient, rng: random.Random) -> dict[str, list[dict[str, Any]]]:
    top_tracks = client.get_top_tracks_overall(limit=1000)
    top_albums = client.get_top_albums_overall(limit=1000)
    top_artists = client.get_top_artists_overall(limit=1000)

    def sample_rows(rows: list[dict], k: int, mapper) -> list[dict[str, Any]]:
        if not rows:
            return []
        picked = rows if len(rows) <= k else rng.sample(rows, k)
        return [mapper(r) for r in picked]

    return {
        "tracks": sample_rows(
            top_tracks,
            40,
            lambda t: {
                "artist": ((t.get("artist", {}) or {}).get("name", "")).strip(),
                "track": t.get("name", "").strip(),
                "playcount": int(str(t.get("playcount", "0")).strip() or "0"),
            },
        ),
        "albums": sample_rows(
            top_albums,
            30,
            lambda a: {
                "artist": ((a.get("artist", {}) or {}).get("name", "")).strip(),
                "album": a.get("name", "").strip(),
                "playcount": int(str(a.get("playcount", "0")).strip() or "0"),
            },
        ),
        "artists": sample_rows(
            top_artists,
            25,
            lambda a: {
                "artist": a.get("name", "").strip(),
                "playcount": int(str(a.get("playcount", "0")).strip() or "0"),
            },
        ),
    }


def _album_playcount(client: LastFMClient, artist: str, album: str, fallback: int) -> int:
    try:
        info = client.get_album_info(artist, album)
        return int(str(info.get("userplaycount", "0")).strip() or "0")
    except Exception:
        return fallback


def recommend_albums(
    client: LastFMClient,
    week_tracks: list[dict],
    weekly_releases: list[dict] | None = None,
    low_history_threshold: int = 2,
    limit: int = 4,
    llm_enabled: bool = False,
    llm_provider: str = "ollama",
    llm_api_key: str = "",
    llm_model: str = "gpt-4.1-mini",
    ollama_base_url: str = "http://localhost:11434",
    ollama_model: str = "LLaMA3.2:1B",
    llm_timeout_seconds: int = 60,
) -> list[dict]:
    weekly_releases = weekly_releases or []
    week_artists: Counter[str] = Counter()
    week_albums: Counter[str] = Counter()
    for track in week_tracks:
        artist = (track.get("artist", {}) or {}).get("name", "").strip()
        album = (track.get("album", {}) or {}).get("#text", "").strip()
        if artist:
            week_artists[artist] += 1
        if artist and album:
            week_albums[f"{artist} - {album}"] += 1

    if not week_artists:
        return []

    album_playcounts, artist_playcounts = build_known_history(client)
    seeds = week_artists.most_common(10)

    similar_artist_scores: dict[str, float] = defaultdict(float)
    for seed_artist, seed_weight in seeds:
        for similar in client.get_similar_artists(seed_artist, limit=25):
            candidate_name = similar.get("name", "").strip()
            score = float(str(similar.get("match", "0")).strip() or "0")
            if candidate_name:
                similar_artist_scores[candidate_name] += score * seed_weight

    ranked_artists = sorted(similar_artist_scores.items(), key=lambda row: row[1], reverse=True)[:50]
    candidates: list[dict[str, Any]] = []
    for artist_name, similarity in ranked_artists:
        artist_history = artist_playcounts.get(artist_name.lower(), 0)
        for album in client.get_top_albums_for_artist(artist_name, limit=10):
            album_name = album.get("name", "").strip()
            if not album_name:
                continue
            key = f"{artist_name} - {album_name}".lower()
            album_history = album_playcounts.get(key, 0)
            # Keep low to medium familiarity candidates; hard cutoff for very known albums happens later (>20).
            if artist_history > 250 and album_history > 40:
                continue
            score = _heuristic_score(similarity, artist_history, album_history)
            candidates.append(
                {
                    "artist": artist_name,
                    "album": album_name,
                    "similarity_score": round(similarity, 4),
                    "artist_history_playcount": artist_history,
                    "album_history_playcount": album_history,
                    "score": score,
                }
            )

    # Add weekly AOTY releases as direct candidates so recommendation rows can carry AOTY score/link context.
    for release in weekly_releases:
        artist_name = str(release.get("artist", "")).strip()
        album_name = str(release.get("album", "")).strip()
        if not artist_name or not album_name:
            continue
        key = f"{artist_name} - {album_name}".lower()
        artist_history = artist_playcounts.get(artist_name.lower(), 0)
        album_history = album_playcounts.get(key, 0)
        release_signal = float(week_artists.get(artist_name, 0))
        similarity = similar_artist_scores.get(artist_name, 0.0) + release_signal
        score = _heuristic_score(max(similarity, 0.1), artist_history, album_history) + 10.0
        candidates.append(
            {
                "artist": artist_name,
                "album": album_name,
                "similarity_score": round(similarity, 4),
                "artist_history_playcount": artist_history,
                "album_history_playcount": album_history,
                "score": score,
            }
        )

    deduped: dict[str, dict[str, Any]] = {}
    for candidate in sorted(candidates, key=lambda row: row["score"], reverse=True):
        key = f"{candidate['artist']} - {candidate['album']}".lower()
        if key not in deduped:
            deduped[key] = candidate
    ranked_candidates = list(deduped.values())
    weekly_keys = {
        f"{str(r.get('artist', '')).strip()} - {str(r.get('album', '')).strip()}".lower()
        for r in weekly_releases
        if str(r.get("artist", "")).strip() and str(r.get("album", "")).strip()
    }
    if weekly_keys:
        weekly_ranked = [row for row in ranked_candidates if f"{row['artist']} - {row['album']}".lower() in weekly_keys]
        other_ranked = [row for row in ranked_candidates if f"{row['artist']} - {row['album']}".lower() not in weekly_keys]
        shortlist = (weekly_ranked + other_ranked)[:80]
    else:
        shortlist = ranked_candidates[:80]

    weekly_shortlist = [row for row in shortlist if f"{row['artist']} - {row['album']}".lower() in weekly_keys]
    non_weekly_shortlist = [row for row in shortlist if f"{row['artist']} - {row['album']}".lower() not in weekly_keys]
    prioritized_shortlist = weekly_shortlist + non_weekly_shortlist
    llm_first = [row for row in shortlist if f"{row['artist']} - {row['album']}".lower() in weekly_keys]
    llm_source_rows = llm_first if llm_first else shortlist

    candidate_pool = [
        {
            "artist": row["artist"],
            "album": row["album"],
            "artist_history_playcount": row["artist_history_playcount"],
            "album_history_playcount": row["album_history_playcount"],
            "heuristic_score": round(float(row["score"]), 3),
        }
        for row in llm_source_rows[:30]
    ]

    llm_selected: list[dict[str, Any]] = []
    if llm_enabled and candidate_pool:
        rng = random.Random()
        history_sample = _sample_history(client, rng)
        week_profile = {
            "top_artists": [{"artist": n, "plays": p} for n, p in week_artists.most_common(15)],
            "top_albums": [{"album": n, "plays": p} for n, p in week_albums.most_common(10)],
            "total_tracks_this_week": len(week_tracks),
        }
        model = ollama_model if llm_provider == "ollama" else llm_model
        try:
            llm_selected = recommend_albums_with_llm(
                provider=llm_provider,
                model=model,
                week_profile=week_profile,
                random_history_sample=history_sample,
                candidate_pool=candidate_pool,
                limit=max(limit * 2, 10),
                timeout=llm_timeout_seconds,
                api_key=llm_api_key,
                ollama_base_url=ollama_base_url,
            )
        except Exception:
            llm_selected = []

    shortlist_by_key = {f"{row['artist']} - {row['album']}".lower(): row for row in shortlist}
    shortlist_by_album: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in shortlist:
        shortlist_by_album[row["album"].lower()].append(row)
    final: list[dict[str, Any]] = []
    seen: set[str] = set()
    artist_counts: Counter[str] = Counter()
    max_albums_per_artist = 2
    target_total = max(1, limit)

    def try_add(artist: str, album: str, score: float, source: str) -> bool:
        key = f"{artist} - {album}".lower()
        if key in seen:
            return False
        artist_key = artist.lower()
        if artist_counts[artist_key] >= max_albums_per_artist:
            return False
        base = shortlist_by_key.get(key, {})
        fallback_plays = int(base.get("album_history_playcount", 0))
        album_playcount = _album_playcount(client, artist, album, fallback=fallback_plays)
        if album_playcount > KNOWN_ALBUM_PLAYS_THRESHOLD:
            return False
        final.append(
            {
                "artist": artist,
                "album": album,
                "score": score,
                "album_playcount": album_playcount,
                "reason": source,
                "source": source,
            }
        )
        seen.add(key)
        artist_counts[artist_key] += 1
        return True

    llm_added = 0
    llm_target = 1 if (llm_enabled and llm_selected) else 0
    for row in llm_selected:
        if llm_added >= llm_target:
            break
        artist = str(row.get("artist", "")).strip()
        album = str(row.get("album", "")).strip()
        key = f"{artist} - {album}".lower()
        if key not in shortlist_by_key and album:
            album_matches = shortlist_by_album.get(album.lower(), [])
            if len(album_matches) == 1:
                artist = str(album_matches[0].get("artist", "")).strip()
                album = str(album_matches[0].get("album", "")).strip()
                key = f"{artist} - {album}".lower()
        if key not in shortlist_by_key:
            query = key.strip(" -")
            if query:
                best = difflib.get_close_matches(query, shortlist_by_key.keys(), n=1, cutoff=0.55)
                if best:
                    matched = shortlist_by_key[best[0]]
                    artist = str(matched.get("artist", "")).strip()
                    album = str(matched.get("album", "")).strip()
                    key = f"{artist} - {album}".lower()
        if key not in shortlist_by_key:
            continue
        added = try_add(
            artist=artist,
            album=album,
            score=float(row.get("fit_score", 0.0)),
            source="LLM",
        )
        if added:
            llm_added += 1
        if len(final) >= target_total:
            return final[:target_total]

    # Heuristic fallback (also filtered by album_playcount <= 20)
    heuristic_cap = 3 if llm_added > 0 else target_total
    heuristic_added = 0
    for row in prioritized_shortlist:
        if heuristic_added >= heuristic_cap:
            break
        added = try_add(
            artist=row["artist"],
            album=row["album"],
            score=float(row.get("score", 0.0)),
            source="heuristic",
        )
        if added:
            heuristic_added += 1
        if len(final) >= target_total:
            break

    # If we still have open slots (e.g., LLM suggestion filtered out), fill with more heuristic picks.
    if len(final) < target_total:
        for row in prioritized_shortlist:
            added = try_add(
                artist=row["artist"],
                album=row["album"],
                score=float(row.get("score", 0.0)),
                source="heuristic",
            )
            if added and len(final) >= target_total:
                break

    return final[:target_total]
