from __future__ import annotations

import re
import unicodedata
from typing import Any
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup, Tag

from .aoty import normalize_album_key

RYM_BASE_URL = "https://rateyourmusic.com"
NEW_MUSIC_URL = f"{RYM_BASE_URL}/new-music/"

NEW_MUSIC_MARKER = "newreleases_itembox"
ARTIST_MARKER = "disco_release"
SEARCH_MARKER = "page_search_results"


def _normalize_name(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _match_key(artist: object, album: object) -> str:
    return f"{_normalize_name(artist)}::{_normalize_name(album)}"


def _slugify(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def _parse_int(value: object) -> int:
    try:
        return int(re.sub(r"[^\d]", "", str(value)) or "0")
    except (TypeError, ValueError):
        return 0


def _browser(url: str, *, headless: bool, timeout_seconds: int, ready_marker: str) -> str:
    try:
        from .browser_fetch import fetch_with_browser
    except Exception:
        return ""
    try:
        return fetch_with_browser(
            url,
            headless=headless,
            timeout_seconds=timeout_seconds,
            ready_marker=ready_marker,
        )
    except Exception:
        return ""


def parse_new_releases(html: str) -> list[dict[str, Any]]:
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, Any]] = []
    for item in soup.select(".newreleases_itembox"):
        if not isinstance(item, Tag):
            continue
        album_el = item.select_one("a.newreleases_item_title") or item.select_one("a.album")
        artist_el = item.select_one("a.artist")
        if not isinstance(album_el, Tag) or not isinstance(artist_el, Tag):
            continue
        album = album_el.get_text(" ", strip=True)
        artist = artist_el.get_text(" ", strip=True)
        if not album or not artist:
            continue
        score_el = item.select_one(".newreleases_avg_rating_stat")
        count_el = item.select_one(".newreleases_ratings_stat")
        score = score_el.get_text(" ", strip=True) if isinstance(score_el, Tag) else ""
        count = _parse_int(count_el.get_text(" ", strip=True)) if isinstance(count_el, Tag) else 0
        href = str(album_el.get("href", "")).strip()
        rows.append(
            {
                "artist": artist,
                "album": album,
                "score": score,
                "count": count,
                "url": urljoin(RYM_BASE_URL, href) if href else "",
            }
        )
    return rows


def parse_artist_discography(html: str) -> list[dict[str, Any]]:
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, Any]] = []
    for item in soup.select(".disco_release"):
        if not isinstance(item, Tag):
            continue
        title_el = item.select_one(".disco_mainline") or item.select_one(".album")
        if not isinstance(title_el, Tag):
            continue
        album = title_el.get_text(" ", strip=True)
        if not album:
            continue
        score_el = item.select_one(".disco_avg_rating")
        count_el = item.select_one(".disco_ratings")
        year_el = item.select_one(".disco_subline") or item.select_one(".disco_year_ymd")
        link = item.select_one("a[href*='/release/']")
        score = score_el.get_text(" ", strip=True) if isinstance(score_el, Tag) else ""
        count = _parse_int(count_el.get_text(" ", strip=True)) if isinstance(count_el, Tag) else 0
        year = year_el.get_text(" ", strip=True) if isinstance(year_el, Tag) else ""
        href = str(link.get("href", "")).strip() if isinstance(link, Tag) else ""
        rows.append(
            {
                "album": album,
                "score": score,
                "count": count,
                "year": year,
                "url": urljoin(RYM_BASE_URL, href) if href else "",
            }
        )
    return rows


def _fetch_artist_rows(
    slug: str,
    *,
    headless: bool,
    timeout_seconds: int,
) -> list[dict[str, Any]]:
    if not slug:
        return []
    html = _browser(
        f"{RYM_BASE_URL}/artist/{slug}/",
        headless=headless,
        timeout_seconds=timeout_seconds,
        ready_marker=ARTIST_MARKER,
    )
    return parse_artist_discography(html)


def _search_artist_slug(
    artist: str,
    *,
    headless: bool,
    timeout_seconds: int,
) -> str:
    html = _browser(
        f"{RYM_BASE_URL}/search?searchterm={quote(artist)}&searchtype=a",
        headless=headless,
        timeout_seconds=timeout_seconds,
        ready_marker=SEARCH_MARKER,
    )
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    target = _normalize_name(artist)
    fallback = ""
    for link in soup.select("a[href*='/artist/']"):
        if not isinstance(link, Tag):
            continue
        name = link.get_text(" ", strip=True)
        href = str(link.get("href", "")).strip()
        if not href or not name:
            continue
        slug = href.rstrip("/").rsplit("/", 1)[-1]
        if not slug or slug.isdigit():
            continue
        if _normalize_name(name) == target:
            return slug
        if not fallback:
            fallback = slug
    return fallback


def fetch_artist_ratings(
    artist: str,
    *,
    headless: bool,
    timeout_seconds: int,
) -> list[dict[str, Any]]:
    artist = str(artist or "").strip()
    if not artist:
        return []
    slug = _slugify(artist)
    rows = _fetch_artist_rows(slug, headless=headless, timeout_seconds=timeout_seconds)
    if rows:
        return rows
    resolved = _search_artist_slug(artist, headless=headless, timeout_seconds=timeout_seconds)
    if resolved and resolved != slug:
        rows = _fetch_artist_rows(resolved, headless=headless, timeout_seconds=timeout_seconds)
    return rows


def _dedupe_requests(requests: list[tuple[str, str]]) -> list[tuple[str, str, str, str]]:
    out: list[tuple[str, str, str, str]] = []
    seen: set[str] = set()
    for artist, album in requests:
        a = str(artist or "").strip()
        al = str(album or "").strip()
        if not a or not al:
            continue
        key = normalize_album_key(a, al)
        if key == "::" or key in seen:
            continue
        seen.add(key)
        out.append((a, al, key, _match_key(a, al)))
    return out


def get_rym_ratings(
    requests: list[tuple[str, str]],
    *,
    browser_enabled: bool = True,
    browser_headless: bool = False,
    browser_timeout_seconds: int = 40,
    max_artist_lookups: int = 15,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    stats: dict[str, Any] = {
        "status": "ok",
        "new_releases": 0,
        "artist_lookups": 0,
        "matched": 0,
    }
    if not browser_enabled:
        stats["status"] = "skipped (browser fallback disabled)"
        return lookup, stats

    reqs = _dedupe_requests(requests)
    if not reqs:
        stats["status"] = "no releases to look up"
        return lookup, stats

    feed_html = _browser(
        NEW_MUSIC_URL,
        headless=browser_headless,
        timeout_seconds=browser_timeout_seconds,
        ready_marker=NEW_MUSIC_MARKER,
    )
    feed = parse_new_releases(feed_html)
    stats["new_releases"] = len(feed)

    feed_index: dict[str, dict[str, Any]] = {}
    for row in feed:
        key = _match_key(row.get("artist", ""), row.get("album", ""))
        if key and key != "::":
            feed_index.setdefault(key, row)

    unmatched: list[tuple[str, str, str, str]] = []
    for artist, album, req_key, match_key in reqs:
        hit = feed_index.get(match_key)
        if hit:
            lookup[req_key] = {**hit, "source": "new-music"}
        else:
            unmatched.append((artist, album, req_key, match_key))

    artists: list[str] = []
    seen_artists: set[str] = set()
    for artist, _album, _req_key, _match_key_value in unmatched:
        norm = _normalize_name(artist)
        if norm and norm not in seen_artists:
            seen_artists.add(norm)
            artists.append(artist)
    artists = artists[: max(max_artist_lookups, 0)]

    for artist in artists:
        stats["artist_lookups"] += 1
        rows = fetch_artist_ratings(
            artist, headless=browser_headless, timeout_seconds=browser_timeout_seconds
        )
        disc_index: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = _match_key(artist, row.get("album", ""))
            if key and key != "::":
                disc_index.setdefault(key, row)
        artist_norm = _normalize_name(artist)
        for req_artist, _album, req_key, match_key in unmatched:
            if req_key in lookup:
                continue
            if _normalize_name(req_artist) != artist_norm:
                continue
            hit = disc_index.get(match_key)
            if hit:
                lookup[req_key] = {**hit, "artist": artist, "source": "artist"}

    stats["matched"] = len(lookup)
    if stats["new_releases"] == 0 and not lookup:
        stats["status"] = "empty (blocked or no data)"
    return lookup, stats
