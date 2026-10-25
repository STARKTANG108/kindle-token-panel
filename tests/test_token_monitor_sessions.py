import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import server


class TokenMonitorSessionsTest(unittest.TestCase):
    NOW = 1792915200.0

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        base = Path(directory.name)
        self.database = base / "sessions.sqlite"
        with sqlite3.connect(self.database) as connection:
            connection.execute("CREATE TABLE sessions (revision INTEGER, entry_json TEXT)")
        for name, value in {
            "SESSION_SQLITE_PATH": str(self.database),
            "DAILY_ARCHIVE_PATH": str(base / "daily.json"),
            "_TPM_HISTORY": []
        }.items():
            replacement = patch.object(server, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)
        clock = patch.object(server.time, "time", return_value=self.NOW)
        clock.start()
        self.addCleanup(clock.stop)

    def timestamp(self, age):
        return datetime.fromtimestamp(self.NOW - age, timezone.utc).isoformat()

    def collect(self, last_used, captured_age=0):
        entry = {
            "client": "codex",
            "sessionId": "test-session",
            "capturedAt": self.timestamp(captured_age),
            "periods": {"today": {
                "totalTokens": 1000,
                "inputTokens": 100,
                "outputTokens": 100,
                "cacheReadTokens": 800,
                "timedDurationMs": 60000,
                "timedOutputTokens": 120,
                "lastUsedAt": last_used
            }}
        }
        with sqlite3.connect(self.database) as connection:
            connection.execute("DELETE FROM sessions")
            connection.execute("INSERT INTO sessions VALUES (?, ?)", (1, json.dumps(entry)))
        return server.get_token_monitor_stats()

    def test_recent_collection_preserves_usage_for_a_historical_session(self):
        today, _, tpm, _, _, active = self.collect(self.timestamp(3600))
        self.assertEqual(today["tokens"], 1000)
        self.assertEqual(active, [])
        self.assertEqual(tpm, 0)

    def test_recent_activity_remains_active_with_an_older_collection_time(self):
        _, _, tpm, _, _, active = self.collect(self.timestamp(60), captured_age=3600)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["client"], "codex")
        self.assertEqual(active[0]["age_sec"], 60)
        self.assertEqual(tpm, 600)

    def test_valid_activity_timestamp_controls_task_visibility(self):
        for last_used in [None, "invalid", self.timestamp(-60), self.timestamp(600)]:
            with self.subTest(last_used=last_used):
                _, _, tpm, _, _, active = self.collect(last_used)
                self.assertEqual(active, [])
                self.assertEqual(tpm, 0)

    def test_activity_inside_the_ten_minute_window_is_visible(self):
        _, _, _, _, _, active = self.collect(self.timestamp(599))
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["age_sec"], 599)


if __name__ == "__main__":
    unittest.main()
