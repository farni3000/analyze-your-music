from __future__ import annotations

import socket
import time
from typing import Any
from urllib.parse import urlparse

import requests


class LastFMClient:
    def __init__(self, api_key: str, username: str, base_url: str):
        self.api_key = api_key
        self.username = username
        self.base_url = base_url
        self.session = requests.Session()
        parsed = urlparse(base_url)
        self.host = parsed.hostname or "ws.audioscrobbler.com"

    def _is_dns_ready(self) -> bool:
        try:
            socket.getaddrinfo(self.host, None)
            return True
        except socket.gaierror:
            return False

    def _get(self, method: str, **params: Any) -> dict[str, Any]:
        query = {
            "method": method,
            "api_key": self.api_key,
            "format": "json",
            **params,
        }
        max_attempts = 8
        last_exc: Exception | None = None
        response = None
        for attempt in range(1, max_attempts + 1):
            try:
                response = self.session.get(self.base_url, params=query, timeout=30)
                response.raise_for_status()
                break
            except requests.RequestException as exc:
                last_exc = exc
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                msg = str(exc).lower()
                dns_error = any(
                    token in msg
                    for token in [
                        "nodename nor servname provided",
                        "name or service not known",
                        "temporary failure in name resolution",
                        "failed to resolve",
                    ]
                )
                retriable = status_code is None or status_code >= 500 or status_code == 429 or dns_error
                if not retriable or attempt == max_attempts:
                    raise RuntimeError(f"Network/API request failed for method '{method}': {exc}") from exc
                if dns_error:
                    dns_wait_started = time.time()
                    while time.time() - dns_wait_started < min(12, 2 + attempt * 1.5):
                        if self._is_dns_ready():
                            break
                        time.sleep(0.4)
                time.sleep(min(8.0, 0.9 * attempt))
        if response is None:
            raise RuntimeError(f"Network/API request failed for method '{method}': {last_exc}")
        data = response.json()
        if "error" in data:
            raise RuntimeError(f"Last.fm API error {data.get('error')}: {data.get('message')}")
        return data

    def iter_recent_tracks(
        self,
        from_ts: int | None = None,
        to_ts: int | None = None,
        limit: int = 200,
    ):
        page = 1
        while True:
            params: dict[str, Any] = {
                "user": self.username,
                "limit": limit,
                "page": page,
                "extended": 1,
            }
            if from_ts is not None:
                params["from"] = from_ts
            if to_ts is not None:
                params["to"] = to_ts
            payload = self._get("user.getrecenttracks", **params)
            block = payload.get("recenttracks", {})
            page_tracks = block.get("track", [])
            if isinstance(page_tracks, dict):
                page_tracks = [page_tracks]
            for track in page_tracks:
                yield track

            attr = block.get("@attr", {})
            total_pages = int(attr.get("totalPages", "1"))
            if page >= total_pages:
                break
            page += 1

    def get_recent_tracks(self, from_ts: int, to_ts: int, limit: int = 200) -> list[dict[str, Any]]:
        return list(self.iter_recent_tracks(from_ts=from_ts, to_ts=to_ts, limit=limit))

    def get_all_recent_tracks(self, limit: int = 200) -> list[dict[str, Any]]:
        return list(self.iter_recent_tracks(limit=limit))

    def get_top_tracks_overall(self, limit: int = 1000) -> list[dict[str, Any]]:
        payload = self._get("user.gettoptracks", user=self.username, period="overall", limit=limit)
        tracks = payload.get("toptracks", {}).get("track", [])
        return tracks if isinstance(tracks, list) else [tracks]

    def get_top_albums_overall(self, limit: int = 1000) -> list[dict[str, Any]]:
        payload = self._get("user.gettopalbums", user=self.username, period="overall", limit=limit)
        albums = payload.get("topalbums", {}).get("album", [])
        return albums if isinstance(albums, list) else [albums]

    def get_top_artists_overall(self, limit: int = 1000) -> list[dict[str, Any]]:
        payload = self._get("user.gettopartists", user=self.username, period="overall", limit=limit)
        artists = payload.get("topartists", {}).get("artist", [])
        return artists if isinstance(artists, list) else [artists]

    def get_similar_artists(self, artist: str, limit: int = 20) -> list[dict[str, Any]]:
        payload = self._get("artist.getsimilar", artist=artist, limit=limit, autocorrect=1)
        artists = payload.get("similarartists", {}).get("artist", [])
        return artists if isinstance(artists, list) else [artists]

    def get_top_tracks_for_artist(self, artist: str, limit: int = 15) -> list[dict[str, Any]]:
        payload = self._get("artist.gettoptracks", artist=artist, limit=limit, autocorrect=1)
        tracks = payload.get("toptracks", {}).get("track", [])
        return tracks if isinstance(tracks, list) else [tracks]

    def get_top_albums_for_artist(self, artist: str, limit: int = 12) -> list[dict[str, Any]]:
        payload = self._get("artist.gettopalbums", artist=artist, limit=limit, autocorrect=1)
        albums = payload.get("topalbums", {}).get("album", [])
        return albums if isinstance(albums, list) else [albums]

    def get_track_info(self, artist: str, track: str) -> dict[str, Any]:
        payload = self._get(
            "track.getInfo",
            artist=artist,
            track=track,
            autocorrect=1,
            username=self.username,
        )
        return payload.get("track", {})

    def get_album_info(self, artist: str, album: str) -> dict[str, Any]:
        payload = self._get(
            "album.getInfo",
            artist=artist,
            album=album,
            autocorrect=1,
            username=self.username,
        )
        return payload.get("album", {})

    def get_artist_tags(self, artist: str, limit: int = 5) -> list[str]:
        payload = self._get("artist.getTopTags", artist=artist, autocorrect=1)
        tags = payload.get("toptags", {}).get("tag", [])
        tags = tags if isinstance(tags, list) else [tags]
        return [t.get("name", "").strip() for t in tags[:limit] if t.get("name")]

    def get_album_tags(self, artist: str, album: str, limit: int = 10) -> list[str]:
        payload = self._get("album.getTopTags", artist=artist, album=album, autocorrect=1)
        tags = payload.get("toptags", {}).get("tag", [])
        tags = tags if isinstance(tags, list) else [tags]
        return [t.get("name", "").strip() for t in tags[:limit] if t.get("name")]
