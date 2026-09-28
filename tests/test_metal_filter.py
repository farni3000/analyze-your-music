from __future__ import annotations

from src.main import (
    ALBUM_TAG_LIMIT,
    ARTIST_TAG_LIMIT,
    _annotate_and_filter_releases,
    _is_metal_tagged,
)


class _StubClient:
    def __init__(self, album_tags=None, artist_tags=None):
        self.album_tags = album_tags or {}
        self.artist_tags = artist_tags or {}
        self.album_calls: list[tuple[str, str, int]] = []
        self.artist_calls: list[tuple[str, int]] = []

    def get_album_tags(self, artist: str, album: str, limit: int = 10) -> list[str]:
        self.album_calls.append((artist, album, limit))
        return list(self.album_tags.get((artist, album), []))

    def get_artist_tags(self, artist: str, limit: int = 5) -> list[str]:
        self.artist_calls.append((artist, limit))
        return list(self.artist_tags.get(artist, []))


def _release(artist: str, album: str) -> dict:
    return {
        "artist": artist,
        "album": album,
        "user_score": "80",
        "user_review_count": 40,
    }


def test_is_metal_tagged_matches_related_genres() -> None:
    for tag in ("Metal", "doom", "Sludge Metal", "stoner rock", "Grunge", "djent", "grindcore", "deathcore", "post-metal"):
        assert _is_metal_tagged([tag]) is True, tag


def test_is_metal_tagged_ignores_unrelated_genres() -> None:
    for tag in ("pop", "jazz", "hip hop", "ambient", "singer-songwriter"):
        assert _is_metal_tagged([tag]) is False, tag


def test_is_metal_tagged_scans_all_tags() -> None:
    assert _is_metal_tagged(["pop", "electronic", "doom"]) is True
    assert _is_metal_tagged([]) is False


def test_annotate_uses_full_album_tag_limit() -> None:
    client = _StubClient(album_tags={("Band", "Record"): ["pop"]})
    rows = _annotate_and_filter_releases(client, [_release("Band", "Record")], {})

    assert client.album_calls == [("Band", "Record", ALBUM_TAG_LIMIT)]
    assert rows[0]["tag_source"] == "album"
    assert rows[0]["is_metal_tagged"] is False


def test_annotate_falls_back_to_artist_tags_when_album_has_none() -> None:
    client = _StubClient(artist_tags={"Band": ["sludge", "doom"]})
    rows = _annotate_and_filter_releases(client, [_release("Band", "Record")], {})

    assert client.artist_calls == [("Band", ARTIST_TAG_LIMIT)]
    assert rows[0]["tag_source"] == "artist"
    assert rows[0]["is_metal_tagged"] is True
    assert rows[0]["tags"] == ["sludge", "doom"]


def test_annotate_marks_metal_from_album_tags() -> None:
    client = _StubClient(album_tags={("Band", "Record"): ["grunge", "alternative rock"]})
    rows = _annotate_and_filter_releases(client, [_release("Band", "Record")], {})

    assert rows[0]["is_metal_tagged"] is True
    assert rows[0]["tag_source"] == "album"
    assert client.artist_calls == [("Band", ARTIST_TAG_LIMIT)]


def test_annotate_merges_album_and_artist_tags() -> None:
    client = _StubClient(
        album_tags={("Band", "Record"): ["2026"]},
        artist_tags={"Band": ["stoner", "doom metal"]},
    )
    rows = _annotate_and_filter_releases(client, [_release("Band", "Record")], {})

    assert rows[0]["tag_source"] == "album+artist"
    assert rows[0]["tags"] == ["2026", "stoner", "doom metal"]
    assert rows[0]["is_metal_tagged"] is True


def test_annotate_survives_tag_lookup_errors() -> None:
    class _FailingClient:
        def get_album_tags(self, artist: str, album: str, limit: int = 10):
            raise RuntimeError("boom")

        def get_artist_tags(self, artist: str, limit: int = 5):
            raise RuntimeError("boom")

    rows = _annotate_and_filter_releases(_FailingClient(), [_release("Band", "Record")], {})

    assert rows[0]["is_metal_tagged"] is False
    assert rows[0]["tag_source"] == "none"
    assert rows[0]["tags"] == []
