from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from src.listening_history import artist_listen_count, get_artist_listen_counts


class _StubClient:
    def __init__(self, artists):
        self._artists = artists

    def get_top_artists_overall(self, limit=1000):
        del limit
        return self._artists


class _FailingClient:
    def get_top_artists_overall(self, limit=1000):
        del limit
        raise AssertionError("get_top_artists_overall should not have been called")


class ListeningHistoryTests(unittest.TestCase):
    def test_artist_listen_count_normalizes_case(self):
        counts = {"taylor swift": 7}
        self.assertEqual(artist_listen_count(counts, "Taylor Swift"), 7)

    def test_get_artist_listen_counts_uses_fresh_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = f"{temp_dir}/history.json"
            payload = {
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "artist_listen_counts": {"radiohead": 9},
                "total_scrobbles": 9,
            }
            with open(path, "w", encoding="utf-8") as file:
                json.dump(payload, file)

            counts, refreshed = get_artist_listen_counts(
                _FailingClient(),
                history_path=path,
                refresh_days=30,
            )

            self.assertFalse(refreshed)
            self.assertEqual(counts.get("radiohead"), 9)

    def test_get_artist_listen_counts_refreshes_stale_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = f"{temp_dir}/history.json"
            stale_payload = {
                "last_updated": (datetime.now(timezone.utc) - timedelta(days=45)).isoformat(),
                "artist_listen_counts": {"old artist": 1},
                "total_scrobbles": 1,
            }
            with open(path, "w", encoding="utf-8") as file:
                json.dump(stale_payload, file)

            artists = [
                {"name": "Caroline Polachek", "playcount": "2"},
                {"name": "Burial", "playcount": "1"},
            ]
            counts, refreshed = get_artist_listen_counts(
                _StubClient(artists),
                history_path=path,
                refresh_days=30,
            )

            self.assertTrue(refreshed)
            self.assertEqual(counts.get("caroline polachek"), 2)
            self.assertEqual(counts.get("burial"), 1)

            with open(path, "r", encoding="utf-8") as file:
                reloaded = json.load(file)
            self.assertEqual(reloaded["artist_listen_counts"]["caroline polachek"], 2)


if __name__ == "__main__":
    unittest.main()
