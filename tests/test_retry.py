"""python3 -m unittest discover tests"""

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import fleet_settings  # noqa: E402
import repo_settings  # noqa: E402
from repo_settings import MAX_ATTEMPTS, MAX_DELAY, ApiError, backoff, gh  # noqa: E402

OK = SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr="")
RESET = SimpleNamespace(returncode=1, stdout='{"id":1,"na', stderr="read: connection reset by peer")


def http(status: int, message: str = "nope") -> SimpleNamespace:
    return SimpleNamespace(returncode=1, stdout=json.dumps({"status": str(status), "message": message}), stderr="")


class Retry(unittest.TestCase):
    def setUp(self):
        self.sleeps: list[float] = []
        patcher = mock.patch.object(repo_settings, "_sleep", self.sleeps.append)
        patcher.start()
        self.addCleanup(patcher.stop)
        silence = mock.patch("sys.stderr", new=mock.MagicMock())
        silence.start()
        self.addCleanup(silence.stop)

    def run_with(self, *results):
        return mock.patch.object(repo_settings.subprocess, "run", side_effect=list(results))

    def test_dropped_connection_is_retried_then_succeeds(self):
        with self.run_with(RESET, RESET, OK) as run:
            self.assertEqual(gh("GET", "repos/x/y"), {"ok": True})
        self.assertEqual(run.call_count, 3)
        self.assertEqual(len(self.sleeps), 2)

    def test_server_errors_and_rate_limits_are_retried(self):
        for failure in (http(502), http(503), http(429), http(403, "API rate limit exceeded")):
            with self.run_with(failure, OK) as run:
                gh("GET", "repos/x/y")
            self.assertEqual(run.call_count, 2)

    def test_client_errors_are_not_retried(self):
        for failure in (http(404), http(403, "Resource not accessible"), http(422)):
            with self.run_with(failure, OK) as run, self.assertRaises(ApiError):
                gh("GET", "repos/x/y")
            self.assertEqual(run.call_count, 1)
        self.assertEqual(self.sleeps, [])

    def test_missing_login_is_not_retried(self):
        no_auth = SimpleNamespace(returncode=1, stdout="", stderr="To get started, run: gh auth login")
        with self.run_with(no_auth, OK) as run, self.assertRaises(ApiError):
            gh("GET", "repos/x/y")
        self.assertEqual(run.call_count, 1)

    def test_gives_up_after_max_attempts(self):
        with self.run_with(*[RESET] * MAX_ATTEMPTS) as run, self.assertRaises(ApiError):
            gh("PUT", "repos/x/y", {"a": 1})
        self.assertEqual(run.call_count, MAX_ATTEMPTS)
        self.assertEqual(len(self.sleeps), MAX_ATTEMPTS - 1)

    def test_post_is_not_retried_blindly(self):
        with self.run_with(RESET, OK) as run, self.assertRaises(ApiError):
            gh("POST", "repos/x/y/rulesets", {"name": "n"})
        self.assertEqual(run.call_count, 1)

    def test_backoff_doubles_with_jitter_and_is_capped(self):
        for attempt, step in ((1, 1), (2, 2), (3, 4), (4, 8)):
            for _ in range(50):
                self.assertTrue(step / 2 <= backoff(attempt) <= step)
        self.assertLessEqual(backoff(20), MAX_DELAY)

    def test_create_does_not_duplicate_when_the_first_post_landed(self):
        with self.run_with(RESET) as run:
            fleet_settings._create("repos/x/y/rulesets", {"name": "n"}, exists=lambda: True)
        self.assertEqual(run.call_count, 1)

    def test_create_retries_when_the_post_did_not_land(self):
        with self.run_with(RESET, OK) as run:
            fleet_settings._create("repos/x/y/rulesets", {"name": "n"}, exists=lambda: False)
        self.assertEqual(run.call_count, 2)

    def test_create_does_not_retry_a_rejected_request(self):
        with self.run_with(http(422), OK) as run, self.assertRaises(ApiError):
            fleet_settings._create("repos/x/y/rulesets", {"name": "n"}, exists=lambda: False)
        self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
