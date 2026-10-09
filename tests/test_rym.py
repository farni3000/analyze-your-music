from src import rym
from src.aoty import normalize_album_key
from src.rym import (
    _match_key,
    _slugify,
    get_rym_ratings,
    parse_artist_discography,
    parse_new_releases,
)

NEW_RELEASES_HTML = """
<div class="newreleases_itembox">
  <a class="newreleases_item_title album" href="/release/album/chat-pile/who-loves-the-sun/">Who Loves the Sun</a>
  <a class="artist" href="/artist/chat-pile">Chat Pile</a>
  <div class="newreleases_item_statbox">
    <span class="newreleases_avg_rating_stat newreleases_stat">3.80</span>
    <span class="newreleases_ratings_stat newreleases_stat">7,487</span>
  </div>
</div>
<div class="newreleases_itembox">
  <a class="newreleases_item_title album" href="/release/album/tinashe/popstar/">Popstar</a>
  <a class="artist" href="/artist/tinashe">Tinashe</a>
  <div class="newreleases_item_statbox">
    <span class="newreleases_avg_rating_stat newreleases_stat">3.75</span>
    <span class="newreleases_ratings_stat newreleases_stat">7,519</span>
  </div>
</div>
"""

ARTIST_HTML = """
<div class="disco_release">
  <a href="/release/album/graveyard/fever/"><img src="/x.jpg"/></a>
  <a class="disco_mainline" href="/release/album/graveyard/fever/">Fever</a>
  <span class="disco_avg_rating">3.28</span>
  <span class="disco_ratings">31</span>
  <span class="disco_subline">2026</span>
</div>
<div class="disco_release">
  <a class="disco_mainline" href="/release/album/graveyard/lightning-birth/">Lightning Birth</a>
  <span class="disco_avg_rating">3.10</span>
  <span class="disco_ratings">2,345</span>
  <span class="disco_subline">2024</span>
</div>
"""


def test_parse_new_releases() -> None:
    rows = parse_new_releases(NEW_RELEASES_HTML)
    assert len(rows) == 2
    assert rows[0]["artist"] == "Chat Pile"
    assert rows[0]["album"] == "Who Loves the Sun"
    assert rows[0]["score"] == "3.80"
    assert rows[0]["count"] == 7487
    assert rows[0]["url"] == "https://rateyourmusic.com/release/album/chat-pile/who-loves-the-sun/"
    assert rows[1]["count"] == 7519


def test_parse_artist_discography() -> None:
    rows = parse_artist_discography(ARTIST_HTML)
    assert len(rows) == 2
    assert rows[0]["album"] == "Fever"
    assert rows[0]["score"] == "3.28"
    assert rows[0]["count"] == 31
    assert rows[0]["year"] == "2026"
    assert rows[0]["url"] == "https://rateyourmusic.com/release/album/graveyard/fever/"
    assert rows[1]["count"] == 2345


def test_slugify() -> None:
    assert _slugify("Cameron Winter") == "cameron-winter"
    assert _slugify("Carly Rae Jepsen") == "carly-rae-jepsen"
    assert _slugify("Teller Bank$") == "teller-bank"


def test_match_key_keeps_parentheticals() -> None:
    continued = _match_key("Carly Rae Jepsen", "Day and Night (Continued)")
    plain = _match_key("Carly Rae Jepsen", "Day and Night")
    assert continued != plain


def test_get_rym_ratings_hybrid_feed_then_artist(monkeypatch) -> None:
    def fake_browser(url, *, headless, timeout_seconds, ready_marker):
        if url == rym.NEW_MUSIC_URL:
            return NEW_RELEASES_HTML
        if "/artist/graveyard/" in url:
            return ARTIST_HTML
        return ""

    monkeypatch.setattr(rym, "_browser", fake_browser)

    lookup, stats = get_rym_ratings(
        [("Chat Pile", "Who Loves the Sun"), ("Graveyard", "Fever")],
        browser_enabled=True,
    )

    chat_key = normalize_album_key("Chat Pile", "Who Loves the Sun")
    grave_key = normalize_album_key("Graveyard", "Fever")
    assert lookup[chat_key]["score"] == "3.80"
    assert lookup[chat_key]["source"] == "new-music"
    assert lookup[grave_key]["score"] == "3.28"
    assert lookup[grave_key]["count"] == 31
    assert lookup[grave_key]["source"] == "artist"
    assert stats["new_releases"] == 2
    assert stats["artist_lookups"] == 1
    assert stats["matched"] == 2


def test_get_rym_ratings_does_not_fuzzily_match_parenthetical(monkeypatch) -> None:
    def fake_browser(url, *, headless, timeout_seconds, ready_marker):
        if url == rym.NEW_MUSIC_URL:
            return ""
        if "/artist/carly-rae-jepsen/" in url:
            return (
                '<div class="disco_release">'
                '<a class="disco_mainline" href="/release/album/carly-rae-jepsen/day-and-night/">Day and Night</a>'
                '<span class="disco_avg_rating">3.67</span>'
                '<span class="disco_ratings">4,116</span>'
                "</div>"
            )
        return ""

    monkeypatch.setattr(rym, "_browser", fake_browser)

    lookup, _ = get_rym_ratings(
        [("Carly Rae Jepsen", "Day and Night (Continued)")],
        browser_enabled=True,
    )

    assert lookup == {}


def test_get_rym_ratings_skips_when_browser_disabled() -> None:
    lookup, stats = get_rym_ratings(
        [("Graveyard", "Fever")], browser_enabled=False, browser_timeout_seconds=1
    )
    assert lookup == {}
    assert "disabled" in stats["status"]
