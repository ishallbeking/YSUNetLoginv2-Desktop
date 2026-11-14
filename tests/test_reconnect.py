import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import reconnect


class ReconnectTests(unittest.TestCase):
    def test_logout_error_still_runs_recovery(self):
        client = Mock()
        client.logout.side_effect = RuntimeError("test-user test-password")
        credentials = ("test-user", "test-password", "test-service")
        report = {}
        with patch.object(reconnect, "make_client", return_value=client), patch.object(
            reconnect, "restore_connection", return_value=True
        ) as recovery:
            self.assertFalse(reconnect.cycle(credentials, report, lambda event: None))
        recovery.assert_called_once()
        self.assertNotIn("test-user", report["logout_error"]["error"])
        self.assertNotIn("test-password", report["logout_error"]["error"])
        self.assertEqual(report["phase"], "completed")

    def test_success_requires_observed_logout_and_actual_login(self):
        client = Mock()
        report = {}
        def restore(credentials, report, emit):
            report["login_attempted"] = True
            report["cas_login_success"] = True
            report["restored"] = True
            return True
        with patch.object(reconnect, "make_client", return_value=client), patch.object(
            reconnect, "observe_offline", return_value=(True, [{"online": False}])
        ), patch.object(reconnect, "internet_check", return_value={"passed": False}), patch.object(
            reconnect, "restore_connection", side_effect=restore
        ):
            self.assertTrue(reconnect.cycle(("test-user", "test-password", "test-service"), report, lambda event: None))
        self.assertTrue(report["offline_observed"])

    def test_login_error_with_recovered_connection_is_verified(self):
        client = Mock()
        client.login.side_effect = RuntimeError("server reported a late error")
        offline = {"online": False, "account_matches": False, "service_matches": False}
        online = {"online": True, "account_matches": True, "service_matches": True}
        report = {}
        with patch.object(reconnect, "make_client", return_value=client), patch.object(
            reconnect, "check_identity", side_effect=[offline, online]
        ), patch.object(reconnect, "internet_check", return_value={"passed": True}):
            self.assertTrue(reconnect.restore_connection(
                ("test-user", "test-password", "test-service"), report, lambda event: None, attempts=1
            ))
        self.assertTrue(report["login_attempted"])
        self.assertTrue(report["restored"])


if __name__ == "__main__":
    unittest.main()
