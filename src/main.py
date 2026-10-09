from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .aoty import fetch_top_weekly_releases, normalize_album_key
from .analyzer import current_week_window, summarize_week
from .config import load_config
from .emailer import send_report_email
from .lastfm import LastFMClient
from .listening_history import artist_listen_count, get_artist_listen_counts
from .recommender import recommend_albums
from .report import render_email_html, render_markdown, write_report
from .rym import get_rym_ratings


STATE_FILE = ".report_state.json"

METAL_TAG_KEYWORDS = (
    "metal",
    "doom",
    "sludge",
    "stoner",
    "grunge",
    "djent",
    "grindcore",
    "deathcore",
)

ALBUM_TAG_LIMIT = 50
ARTIST_TAG_LIMIT = 20


def _merge_tags(*tag_lists: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for tags in tag_lists:
        for tag in tags:
            cleaned = str(tag).strip()
            key = cleaned.lower()
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(cleaned)
    return merged


def _is_metal_tagged(tags: list[str]) -> bool:
    for tag in tags:
        normalized = str(tag).lower()
        if any(keyword in normalized for keyword in METAL_TAG_KEYWORDS):
            return True
    return False


def _parse_float(value: object) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return 0.0


def _parse_int(value: object) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _release_flags(release: dict, artist_listen_counts: dict[str, int]) -> dict[str, bool]:
    artist = str(release.get("artist", "")).strip()
    artist_plays = artist_listen_count(artist_listen_counts, artist)
    user_score = _parse_float(release.get("user_score", ""))
    critic_score = _parse_float(release.get("critic_score", ""))
    user_reviews = _parse_int(release.get("user_review_count", release.get("review_count", 0)))
    critic_reviews = _parse_int(release.get("critic_review_count", 0))
    artist_rule = artist_plays > 10
    user_rule = user_score > 78 and user_reviews > 30
    critic_rule = critic_score > 77 and critic_reviews > 5
    big_reviews_rule = user_reviews > 800
    return {
        "artist_rule": artist_rule,
        "user_rule": user_rule,
        "critic_rule": critic_rule,
        "big_reviews_rule": big_reviews_rule,
    }


def _annotate_and_filter_releases(
    client: LastFMClient,
    releases: list[dict],
    artist_listen_counts: dict[str, int],
) -> list[dict]:
    tags_cache: dict[str, tuple[list[str], str]] = {}
    out: list[dict] = []
    for release in releases:
        artist = str(release.get("artist", "")).strip()
        album = str(release.get("album", "")).strip()
        flags = _release_flags(release, artist_listen_counts)
        include = any(flags.values())
        if not include:
            continue

        key = normalize_album_key(artist, album)
        cached = tags_cache.get(key)
        if cached is None:
            album_tags: list[str] = []
            artist_tags: list[str] = []
            if artist and album:
                try:
                    album_tags = client.get_album_tags(artist, album, limit=ALBUM_TAG_LIMIT)
                except Exception:
                    album_tags = []
            if artist:
                try:
                    artist_tags = client.get_artist_tags(artist, limit=ARTIST_TAG_LIMIT)
                except Exception:
                    artist_tags = []
            tags = _merge_tags(album_tags, artist_tags)
            if album_tags and artist_tags:
                source = "album+artist"
            elif album_tags:
                source = "album"
            elif artist_tags:
                source = "artist"
            else:
                source = "none"
            cached = (tags, source)
            tags_cache[key] = cached
        tags, source = cached
        has_metal_tag = _is_metal_tagged(tags)

        row = dict(release)
        row["artist_plays"] = artist_listen_count(artist_listen_counts, artist)
        row["highlight_artist_plays"] = flags["artist_rule"]
        row["highlight_artist_plays_super"] = row["artist_plays"] > 1000
        row["highlight_user_score"] = flags["user_rule"]
        row["highlight_user_reviews"] = flags["big_reviews_rule"]
        row["highlight_critic_score"] = flags["critic_rule"]
        row["highlight_critic_reviews"] = flags["critic_rule"]
        row["is_metal_tagged"] = has_metal_tag
        row["tags"] = tags
        row["tag_source"] = source
        out.append(row)
    return out


def _attach_rym_ratings(releases: list[dict], lookup: dict[str, dict]) -> None:
    for row in releases:
        key = normalize_album_key(str(row.get("artist", "")), str(row.get("album", "")))
        match = lookup.get(key, {})
        row["rym_score"] = str(match.get("score", "")).strip()
        row["rym_rating_count"] = int(match.get("count", 0) or 0)
        row["rym_url"] = str(match.get("url", "")).strip()
        row["rym_album"] = str(match.get("album", "")).strip()
        row["rym_source"] = str(match.get("source", "")).strip()


def _enrich_recommendations_with_aoty(
    recommendations: list[dict],
    weekly_releases: list[dict],
) -> list[dict]:
    lookup: dict[str, dict] = {}
    for row in weekly_releases:
        key = normalize_album_key(str(row.get("artist", "")), str(row.get("album", "")))
        if not key or key == "::":
            continue
        current = lookup.get(key)
        if current is None:
            lookup[key] = row
            continue
        current_score = str(current.get("user_score", "")).strip()
        next_score = str(row.get("user_score", "")).strip()
        if (not current_score and next_score) or (
            str(current.get("url", "")).strip() == "" and str(row.get("url", "")).strip() != ""
        ):
            lookup[key] = row

    enriched: list[dict] = []
    for rec in recommendations:
        rec_row = dict(rec)
        key = normalize_album_key(str(rec_row.get("artist", "")), str(rec_row.get("album", "")))
        match = lookup.get(key, {})
        rec_row["aoty_user_score"] = str(match.get("user_score", "")).strip() or "n/a"
        rec_row["aoty_url"] = str(match.get("url", "")).strip()
        enriched.append(rec_row)
    return enriched


def _drop_recommendations_in_release_section(
    recommendations: list[dict],
    weekly_releases: list[dict],
    limit: int,
) -> list[dict]:
    release_keys = {
        normalize_album_key(str(row.get("artist", "")), str(row.get("album", "")))
        for row in weekly_releases
    }
    release_keys.discard("::")

    out: list[dict] = []
    seen: set[str] = set()
    for rec in recommendations:
        key = normalize_album_key(str(rec.get("artist", "")), str(rec.get("album", "")))
        if not key or key == "::":
            continue
        if key in release_keys:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(rec)
        if len(out) >= limit:
            break
    return out


def run_once() -> str:
    config = load_config()
    client = LastFMClient(config.api_key, config.username, config.base_url)
    window = current_week_window(config.timezone)
    summary, week_tracks = summarize_week(client, window)
    aoty_status = "ok"
    try:
        weekly_releases_all = fetch_top_weekly_releases(
            aoty_base_url=config.aoty_base_url,
            limit=200,
            browser_enabled=config.aoty_browser_enabled,
            browser_headless=config.aoty_browser_headless,
            browser_timeout_seconds=config.aoty_browser_timeout_seconds,
        )
        if not weekly_releases_all:
            aoty_status = "empty (blocked or no releases)"
    except Exception as exc:
        weekly_releases_all = []
        aoty_status = f"error: {type(exc).__name__}: {exc}"
    try:
        artist_listen_counts, _ = get_artist_listen_counts(
            client,
            history_path=config.listening_history_path,
            refresh_days=config.listening_history_refresh_days,
        )
    except Exception:
        artist_listen_counts = {}
    weekly_releases = _annotate_and_filter_releases(
        client=client,
        releases=weekly_releases_all,
        artist_listen_counts=artist_listen_counts,
    )
    rym_status = "disabled"
    rym_stats: dict = {}
    if config.rym_enabled:
        rym_requests = [
            (str(row.get("artist", "")), str(row.get("album", ""))) for row in weekly_releases
        ]
        try:
            rym_lookup, rym_stats = get_rym_ratings(
                rym_requests,
                browser_enabled=config.aoty_browser_enabled,
                browser_headless=config.aoty_browser_headless,
                browser_timeout_seconds=config.rym_browser_timeout_seconds,
                max_artist_lookups=config.rym_max_artist_lookups,
            )
            rym_status = str(rym_stats.get("status", "ok"))
        except Exception as exc:
            rym_lookup = {}
            rym_status = f"error: {type(exc).__name__}: {exc}"
        _attach_rym_ratings(weekly_releases, rym_lookup)
    recommendation_fetch_limit = max(config.recommendation_limit * 3, config.recommendation_limit + 8)
    recommendations = recommend_albums(
        client,
        week_tracks=week_tracks,
        weekly_releases=[],
        low_history_threshold=config.low_history_threshold,
        limit=recommendation_fetch_limit,
        llm_enabled=config.llm_enabled,
        llm_provider=config.llm_provider,
        llm_api_key=config.llm_api_key,
        llm_model=config.llm_model,
        ollama_base_url=config.ollama_base_url,
        ollama_model=config.ollama_model,
        llm_timeout_seconds=config.llm_timeout_seconds,
    )
    recommendations = _drop_recommendations_in_release_section(
        recommendations,
        weekly_releases=weekly_releases_all,
        limit=config.recommendation_limit,
    )
    recommendations = _enrich_recommendations_with_aoty(recommendations, weekly_releases_all)
    release_page_url = "https://rateyourmusic.com/new-music/"
    debug_notes = [
        f"AOTY base URL: {config.aoty_base_url}",
        f"AOTY fetch: {aoty_status}",
        f"AOTY browser fallback: enabled={config.aoty_browser_enabled} headless={config.aoty_browser_headless} timeout={config.aoty_browser_timeout_seconds}s",
        f"Releases before filtering: {len(weekly_releases_all)}",
        f"RYM fetch: {rym_status}",
        f"RYM enriched rows: {sum(1 for row in weekly_releases if row.get('rym_score'))}"
        f" of {len(weekly_releases)} (new-music items: {rym_stats.get('new_releases', 0)},"
        f" artist lookups: {rym_stats.get('artist_lookups', 0)})",
        f"LLM enabled: {config.llm_enabled} (provider: {config.llm_provider})",
        f"Email enabled: {config.email_enabled}",
    ]
    content = render_markdown(
        config.username,
        window,
        summary,
        recommendations,
        weekly_releases=weekly_releases,
        artist_listen_counts=artist_listen_counts,
        release_highlight_min_artist_listens=config.release_highlight_min_artist_listens,
        release_page_url=release_page_url,
        debug_notes=debug_notes,
    )
    html_content = render_email_html(
        config.username,
        window,
        summary,
        recommendations,
        weekly_releases=weekly_releases,
        artist_listen_counts=artist_listen_counts,
        release_highlight_min_artist_listens=config.release_highlight_min_artist_listens,
        release_page_url=release_page_url,
    )
    path = write_report(config.output_dir, window, content)
    if config.email_enabled:
        send_report_email(
            config,
            report_path=path,
            report_text_body=content,
            report_html_body=html_content,
        )
    return path


def already_ran_this_week(tz_name: str) -> bool:
    if not os.path.exists(STATE_FILE):
        return False
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)
    last_run = state.get("last_run", "")
    if not last_run:
        return False

    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    last = datetime.fromisoformat(last_run).astimezone(tz)
    return now.isocalendar()[:2] == last.isocalendar()[:2]


def mark_ran() -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_run": datetime.now().isoformat()}, f)


def run_scheduler(check_interval_seconds: int = 60) -> None:
    config = load_config()
    tz = ZoneInfo(config.timezone)
    while True:
        now = datetime.now(tz)
        at_or_after_target = (now.hour, now.minute) >= (config.friday_run_hour, config.friday_run_minute)
        if now.weekday() == 4 and at_or_after_target and not already_ran_this_week(config.timezone):
            path = run_once()
            mark_ran()
            print(f"Generated weekly report: {path}")
        time.sleep(check_interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Weekly Last.fm summary and recommendations.")
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="Run as a loop and generate one report every Friday.",
    )
    parser.add_argument(
        "--check-interval-seconds",
        type=int,
        default=60,
        help="Used with --schedule. Number of seconds between checks.",
    )
    args = parser.parse_args()

    try:
        if args.schedule:
            run_scheduler(check_interval_seconds=args.check_interval_seconds)
            return

        path = run_once()
        print(f"Generated report: {path}")
    except Exception as exc:
        print(f"Run failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
