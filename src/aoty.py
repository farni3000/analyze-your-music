from __future__ import annotations

import json
import re
import time
import unicodedata
from typing import Any
from urllib.parse import unquote, urljoin

import requests
from bs4 import BeautifulSoup, Tag


def _base_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }


def _blocked_html(text: str) -> bool:
    lower = text.lower()
    blocked_markers = [
        "just a moment",
        "attention required! | cloudflare",
        "cf-chl-widget",
        "challenges.cloudflare.com",
        "performing security verification",
    ]
    if any(marker in lower for marker in blocked_markers):
        return True
    if "<title>" in lower:
        title = lower.split("<title>", 1)[1].split("</title>", 1)[0]
        if "moment" in title or "cloudflare" in title:
            return True
    return False


def _looks_like_jina_markdown(text: str) -> bool:
    lower = text.lower().lstrip()
    return lower.startswith("title:") and "url source:" in lower and "markdown content:" in lower


def _parse_count_from_parens(text: str) -> int:
    match = re.search(r"\(([\d,]+)\)", text)
    if not match:
        return 0
    return int(match.group(1).replace(",", ""))


def _parse_float_like(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return -1.0


def _extract_scores_from_album_block(block: Tag) -> dict[str, Any]:
    out = {
        "critic_score": "",
        "critic_review_count": 0,
        "user_score": "",
        "user_review_count": 0,
    }

    for row in block.select(".ratingRow"):
        if not isinstance(row, Tag):
            continue
        score_el = row.select_one(".ratingBlock .rating")
        score = score_el.get_text(" ", strip=True) if isinstance(score_el, Tag) else ""

        label_els = row.select(".ratingText")
        if not label_els:
            continue
        label = label_els[0].get_text(" ", strip=True).lower()
        count_text = label_els[1].get_text(" ", strip=True) if len(label_els) > 1 else ""
        count = _parse_count_from_parens(count_text)

        if label == "user score":
            out["user_score"] = score
            out["user_review_count"] = count
        elif label == "critic score":
            out["critic_score"] = score
            out["critic_review_count"] = count
    return out


def _extract_from_album_blocks(soup: BeautifulSoup, base_url: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for block in soup.select("div.albumBlock"):
        if not isinstance(block, Tag):
            continue
        album_el = block.select_one(".albumTitle")
        if not isinstance(album_el, Tag):
            continue
        album = album_el.get_text(" ", strip=True)
        if not album:
            continue

        artist_el = block.select_one(".artistTitle")
        artist = artist_el.get_text(" ", strip=True) if isinstance(artist_el, Tag) else ""
        if not artist:
            artist_link = block.select_one("a[href*='/artist/']")
            artist = artist_link.get_text(" ", strip=True) if isinstance(artist_link, Tag) else ""
        if not artist:
            image = block.select_one("img[alt]")
            alt = image.get("alt", "") if isinstance(image, Tag) else ""
            if isinstance(alt, str) and " - " in alt:
                artist = alt.split(" - ", 1)[0].strip()
        if not artist:
            artist = "Unknown Artist"

        album_link = block.select_one("a[href*='/album/']")
        href = ""
        if isinstance(album_link, Tag):
            href = str(album_link.get("href", "")).strip()
        url = urljoin(base_url, href) if href else ""

        scores = _extract_scores_from_album_block(block)
        rows.append(
            {
                "artist": artist,
                "album": album,
                "critic_score": scores["critic_score"],
                "critic_review_count": scores["critic_review_count"],
                "user_score": scores["user_score"],
                "user_review_count": scores["user_review_count"],
                # Backward compatibility with existing report usage.
                "review_count": scores["user_review_count"],
                "url": url,
            }
        )
    return rows


def _extract_from_json_ld(soup: BeautifulSoup, base_url: str) -> list[dict[str, Any]]:
    albums: list[dict[str, Any]] = []
    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
    for script in scripts:
        raw = script.string or script.get_text(strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        stack: list[Any] = payload if isinstance(payload, list) else [payload]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
                continue
            if not isinstance(node, dict):
                continue
            stack.extend(node.values())
            node_type = str(node.get("@type", "")).lower()
            if "album" not in node_type:
                continue
            album = str(node.get("name", "")).strip()
            if not album:
                continue
            by_artist = node.get("byArtist")
            artist = ""
            if isinstance(by_artist, dict):
                artist = str(by_artist.get("name", "")).strip()
            elif isinstance(by_artist, str):
                artist = by_artist.strip()
            agg = node.get("aggregateRating") if isinstance(node.get("aggregateRating"), dict) else {}
            review_count = int(str(agg.get("ratingCount", "0")).replace(",", "") or "0")
            url = urljoin(base_url, str(node.get("url", "")).strip())
            albums.append(
                {
                    "artist": artist or "Unknown Artist",
                    "album": album,
                    "critic_score": "",
                    "critic_review_count": 0,
                    "user_score": "",
                    "user_review_count": review_count,
                    "review_count": review_count,
                    "url": url,
                }
            )
    return albums


def _extract_from_jina_links(text: str, url_pattern: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    entry_regex = re.compile(
        rf"\[!\[Image\s+\d+:\s*(?P<title>[^\]]+)\]\([^)]+\)\]\((?P<url>https?://{url_pattern}[^\)]+)\)",
        flags=re.IGNORECASE,
    )
    matches = list(entry_regex.finditer(text))
    if not matches:
        return rows

    for idx, match in enumerate(matches):
        title = match.group("title").strip()
        url = match.group("url").strip()
        block_start = match.end()
        block_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        block = text[block_start:block_end]

        artist = ""
        album = ""

        artist_album_match = re.search(
            rf"\[(?P<artist>[^\]]+)\]\(https?://{url_pattern.replace('/album/', '/artist/')}[^\)]+\)\[(?P<album>[^\]]+)\]\({re.escape(url)}\)",
            block,
            flags=re.IGNORECASE,
        )
        if artist_album_match:
            artist = artist_album_match.group("artist").strip()
            album = artist_album_match.group("album").strip()

        if not album:
            album_match = re.search(rf"\[(?P<album>[^\]]+)\]\({re.escape(url)}\)", block)
            if album_match:
                album = album_match.group("album").strip()

        if (not artist or not album) and " - " in title:
            t_artist, t_album = [part.strip() for part in title.split(" - ", 1)]
            artist = artist or t_artist
            album = album or t_album

        if not album:
            continue
        if not artist:
            artist = "Unknown Artist"

        score_matches = re.findall(
            r"(?P<score>\d{1,3}(?:\.\d+)?)\s*\n+\s*(?P<label>user|critic)\s+score\s*\n+\s*\((?P<count>[\d,]+)\)",
            block,
            flags=re.IGNORECASE,
        )
        user_score = ""
        user_reviews = 0
        critic_score = ""
        critic_reviews = 0
        for score, label, count in score_matches:
            if label.lower() == "user":
                user_score = score
                user_reviews = int(count.replace(",", ""))
            elif label.lower() == "critic":
                critic_score = score
                critic_reviews = int(count.replace(",", ""))

        rows.append(
            {
                "artist": artist,
                "album": album,
                "critic_score": critic_score,
                "critic_review_count": critic_reviews,
                "user_score": user_score,
                "user_review_count": user_reviews,
                "review_count": user_reviews,
                "url": url,
            }
        )

    return rows


def _fetch_with_browser(url: str, *, headless: bool, timeout_seconds: int) -> str:
    try:
        from .browser_fetch import fetch_with_browser
    except Exception:
        return ""
    return fetch_with_browser(url, headless=headless, timeout_seconds=timeout_seconds)


def _try_fetch_html(
    url: str,
    *,
    browser_enabled: bool = False,
    browser_headless: bool = False,
    browser_timeout_seconds: int = 40,
) -> str:
    text = ""
    try:
        response = requests.get(url, headers=_base_headers(), timeout=30)
        response.raise_for_status()
        text = response.text
        if text and not _blocked_html(text) and not _looks_like_jina_markdown(text):
            return text
    except requests.RequestException:
        pass

    if browser_enabled:
        browser_text = _fetch_with_browser(
            url,
            headless=browser_headless,
            timeout_seconds=browser_timeout_seconds,
        )
        if browser_text and not _blocked_html(browser_text) and not _looks_like_jina_markdown(browser_text):
            return browser_text

    return text


def _aoty_candidates(
    aoty_base_url: str,
    *,
    browser_enabled: bool = False,
    browser_headless: bool = False,
    browser_timeout_seconds: int = 40,
) -> tuple[list[dict[str, Any]], str]:
    url = urljoin(aoty_base_url.rstrip("/") + "/", "releases/this-week/")
    raw = ""
    rows: list[dict[str, Any]] = []

    def _rows_from_html(html: str) -> list[dict[str, Any]]:
        if not html or _blocked_html(html) or _looks_like_jina_markdown(html):
            return []
        soup = BeautifulSoup(html, "html.parser")
        parsed = _extract_from_album_blocks(soup, aoty_base_url)
        if not parsed:
            parsed = _extract_from_json_ld(soup, aoty_base_url)
        return parsed

    for attempt in range(3):
        try:
            raw = _try_fetch_html(url)
        except requests.RequestException:
            raw = ""
        rows = _rows_from_html(raw)
        if rows:
            return rows, raw
        if attempt < 2:
            time.sleep(1.0 + attempt)

    if browser_enabled:
        browser_raw = _fetch_with_browser(
            url,
            headless=browser_headless,
            timeout_seconds=browser_timeout_seconds,
        )
        browser_rows = _rows_from_html(browser_raw)
        if browser_rows:
            return browser_rows, browser_raw
        raw = browser_raw or raw

    try:
        jina_text = _try_fetch_html("https://r.jina.ai/http://www.albumoftheyear.org/releases/this-week/")
    except requests.RequestException:
        jina_text = ""
    if jina_text:
        rows = _extract_from_jina_links(jina_text, r"www\.albumoftheyear\.org/album/")
    return rows, jina_text or raw


def normalize_album_key(artist: str, album: str) -> str:
    def norm(s: str) -> str:
        s = unquote((s or "").lower())
        s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
        s = s.replace("&amp;", "&")
        s = re.sub(r"\(.*?\)", " ", s)
        s = re.sub(r"[^a-z0-9]+", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    return f"{norm(artist)}::{norm(album)}"


def _dedupe_and_rank(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for item in items:
        artist = str(item.get("artist", "")).strip() or "Unknown Artist"
        album = str(item.get("album", "")).strip()
        if not album:
            continue

        url = str(item.get("url", "")).strip()
        key = url.lower() if url else f"{artist.lower()}::{album.lower()}"
        row = {
            "artist": artist,
            "album": album,
            "critic_score": str(item.get("critic_score", "")).strip(),
            "critic_review_count": int(item.get("critic_review_count", 0) or 0),
            "user_score": str(item.get("user_score", "")).strip(),
            "user_review_count": int(item.get("user_review_count", item.get("review_count", 0)) or 0),
            "review_count": int(item.get("user_review_count", item.get("review_count", 0)) or 0),
            "url": url,
        }
        prev = deduped.get(key)
        if prev is None:
            deduped[key] = row
            continue
        if row["user_review_count"] > prev["user_review_count"]:
            deduped[key] = row
            continue
        if row["user_review_count"] == prev["user_review_count"]:
            if _parse_float_like(row["user_score"]) > _parse_float_like(prev["user_score"]):
                deduped[key] = row
                continue
            row_score_fields = int(bool(row["critic_score"])) + int(bool(row["user_score"]))
            prev_score_fields = int(bool(prev["critic_score"])) + int(bool(prev["user_score"]))
            if row_score_fields > prev_score_fields:
                deduped[key] = row

    ranked = sorted(
        deduped.values(),
        key=lambda r: (
            r["user_review_count"],
            _parse_float_like(r["user_score"]),
            r["critic_review_count"],
            _parse_float_like(r["critic_score"]),
        ),
        reverse=True,
    )
    return ranked[:limit]


def fetch_top_weekly_releases(
    aoty_base_url: str,
    limit: int = 8,
    *,
    browser_enabled: bool = False,
    browser_headless: bool = False,
    browser_timeout_seconds: int = 40,
) -> list[dict[str, Any]]:
    aoty_rows, _ = _aoty_candidates(
        aoty_base_url,
        browser_enabled=browser_enabled,
        browser_headless=browser_headless,
        browser_timeout_seconds=browser_timeout_seconds,
    )
    ranked_aoty = _dedupe_and_rank(aoty_rows, limit=limit)
    return ranked_aoty if ranked_aoty else []
