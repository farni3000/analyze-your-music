from src import aoty
from src.aoty import _aoty_candidates, _blocked_html, _extract_from_jina_links


def test_extract_from_jina_links_parses_artist_album_and_scores_per_block() -> None:
    markdown = """
[![Image 5: Drake - ICEMAN](https://cdn2.albumoftheyear.org/200x0/album/1370239-iceman.jpg)](http://www.albumoftheyear.org/album/1370239-drake-iceman.php)

[Drake](http://www.albumoftheyear.org/artist/719-drake/)[ICEMAN](http://www.albumoftheyear.org/album/1370239-drake-iceman.php)

45

critic score

(4)

55

user score

(7,771)

[![Image 6: Kevin Morby - Little Wide Open](https://cdn2.albumoftheyear.org/200x0/album/1677209-little-wide-open.jpg)](http://www.albumoftheyear.org/album/1677209-kevin-morby-little-wide-open.php)

[Kevin Morby](http://www.albumoftheyear.org/artist/4973-kevin-morby/)[Little Wide Open](http://www.albumoftheyear.org/album/1677209-kevin-morby-little-wide-open.php)

81

critic score

(12)

79

user score

(80)
"""
    rows = _extract_from_jina_links(markdown, r"www\.albumoftheyear\.org/album/")

    assert len(rows) == 2
    assert rows[0]["artist"] == "Drake"
    assert rows[0]["album"] == "ICEMAN"
    assert rows[0]["critic_score"] == "45"
    assert rows[0]["critic_review_count"] == 4
    assert rows[0]["user_score"] == "55"
    assert rows[0]["user_review_count"] == 7771
    assert rows[1]["artist"] == "Kevin Morby"
    assert rows[1]["album"] == "Little Wide Open"
    assert rows[1]["critic_score"] == "81"
    assert rows[1]["critic_review_count"] == 12
    assert rows[1]["user_score"] == "79"
    assert rows[1]["user_review_count"] == 80


def test_extract_from_jina_links_uses_title_fallback_when_artist_line_missing() -> None:
    markdown = """
[![Image 10: Jeff Parker - Happy Today](https://cdn2.albumoftheyear.org/200x0/album/1751371-happy-today.jpg)](http://www.albumoftheyear.org/album/1751371-jeff-parker-happy-today.php)

Jeff Parker & ETA IVtet

[Happy Today](http://www.albumoftheyear.org/album/1751371-jeff-parker-happy-today.php)

85

critic score

(6)

79

user score

(21)
"""
    rows = _extract_from_jina_links(markdown, r"www\.albumoftheyear\.org/album/")

    assert len(rows) == 1
    assert rows[0]["artist"] == "Jeff Parker"
    assert rows[0]["album"] == "Happy Today"
    assert rows[0]["critic_score"] == "85"
    assert rows[0]["user_score"] == "79"


def test_blocked_html_detects_localized_and_turnstile_challenges() -> None:
    assert _blocked_html("<html><head><title>Just a moment...</title></head></html>") is True
    assert _blocked_html("<html><head><title>Nur einen Moment…</title></head></html>") is True
    assert _blocked_html("<div class='cf-chl-widget-abc'></div>") is True
    assert _blocked_html("<script src='https://challenges.cloudflare.com/x.js'></script>") is True
    assert _blocked_html("<html><head><title>This Week's New Album Releases</title></head></html>") is False


def test_aoty_candidates_uses_browser_fallback(monkeypatch) -> None:
    monkeypatch.setattr(aoty.time, "sleep", lambda *_: None)
    monkeypatch.setattr(aoty, "_try_fetch_html", lambda url: "<title>Just a moment...</title>")
    html = (
        '<div class="albumBlock">'
        '<div class="albumTitle">Album X</div>'
        '<div class="artistTitle">Artist Y</div>'
        '<a href="/album/1-x.php">link</a>'
        "</div>"
    )
    calls: list[tuple[bool, int]] = []

    def fake_browser(url, *, headless, timeout_seconds):
        calls.append((headless, timeout_seconds))
        return html

    monkeypatch.setattr(aoty, "_fetch_with_browser", fake_browser)

    rows, _ = _aoty_candidates(
        "https://example.com",
        browser_enabled=True,
        browser_headless=True,
        browser_timeout_seconds=5,
    )

    assert len(rows) == 1
    assert rows[0]["album"] == "Album X"
    assert rows[0]["artist"] == "Artist Y"
    assert calls == [(True, 5)]


def test_aoty_candidates_skips_browser_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(aoty.time, "sleep", lambda *_: None)
    monkeypatch.setattr(aoty, "_try_fetch_html", lambda url: "")

    def boom(*args, **kwargs):
        raise AssertionError("browser should not be called")

    monkeypatch.setattr(aoty, "_fetch_with_browser", boom)

    rows, _ = _aoty_candidates("https://example.com", browser_enabled=False)

    assert rows == []
