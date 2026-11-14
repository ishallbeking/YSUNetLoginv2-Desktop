import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import desktop_backend as backend

class DesktopPolicyTests(unittest.TestCase):
    def test_unknown_state_never_triggers_login(self):
        p = backend.RetryPolicy()
        for enabled, online, busy in [(True, None, False), (False, False, False), (True, False, True)]:
            self.assertFalse(p.allowed(enabled, online, busy, 0))
        self.assertTrue(p.allowed(True, False, False, 0))

    def test_retry_backoff_and_three_failure_limit(self):
        p = backend.RetryPolicy()
        p.failed(30, 0)
        self.assertFalse(p.allowed(True, False, False, 29))
        self.assertTrue(p.allowed(True, False, False, 30))
        p.failed(30, 30)
        self.assertFalse(p.allowed(True, False, False, 89))
        p.failed(30, 90)
        self.assertFalse(p.allowed(True, False, False, 10000))
        p.reset()
        self.assertTrue(p.allowed(True, False, False, 10001))

    def test_failed_status_does_not_issue_login(self):
        c = Mock()
        with patch.object(backend, "make_client", return_value=c), patch.object(backend, "inspect", side_effect=TimeoutError()):
            with self.assertRaises(TimeoutError):
                backend.network_operation("login")
        c.login.assert_not_called()
        c.client.close.assert_called_once()

    def test_other_online_account_never_replaced_automatically(self):
        c = Mock()
        state = {"online": True, "account_matches": False, "service_matches": True}
        with patch.object(backend, "make_client", return_value=c), patch.object(backend, "inspect", return_value=state), patch.object(backend, "credentials", return_value=("test", "secret", "中国电信")):
            with self.assertRaises(RuntimeError):
                backend.network_operation("login")
        c.login.assert_not_called()
        c.logout.assert_not_called()

    def test_save_rejects_newlines_and_preserves_original(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".deployment") as directory:
            path = Path(directory) / "credentials.txt"
            backend.save_credentials("test-account", "test-password", "中国电信", path)
            self.assertEqual(backend.read_credentials(path), ("test-account", "test-password", "中国电信"))
            previous = path.read_bytes()
            with self.assertRaises(ValueError):
                backend.save_credentials("invalid\naccount", "password", "中国电信", path)
            self.assertEqual(path.read_bytes(), previous)

    def test_errors_never_echo_server_credentials(self):
        message = backend.error_message(RuntimeError("username SECRET password TICKET"))
        self.assertNotIn("SECRET", message)
        self.assertNotIn("TICKET", message)
