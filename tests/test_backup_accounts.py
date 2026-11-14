import contextlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import account_profiles as profiles
import desktop_backend as backend
import reconnect

PRIMARY = ("primary-user", "primary-secret", "中国电信")
BACKUP = ("backup-user", "backup-secret", "中国联通")
PROFILES = [("primary", PRIMARY), ("backup", BACKUP)]
OFFLINE = {"online": False, "account_matches": False, "service_matches": False}
BACKUP_ONLINE = {"online": True, "account_matches": True, "service_matches": True, "account_profile": "backup"}


class BackupPolicyTests(unittest.TestCase):
    def test_exactly_three_primary_then_three_backup_failures(self):
        policy = backend.RetryPolicy(backup_available=True)
        sequence = []
        for number in range(6):
            self.assertTrue(policy.allowed(True, False, False, policy.next_attempt))
            sequence.append(policy.profile)
            policy.failed(15, policy.next_attempt)
        self.assertEqual(sequence, ["primary"] * 3 + ["backup"] * 3)
        self.assertEqual(policy.counts, {"primary": 3, "backup": 3})
        self.assertTrue(policy.exhausted)
        self.assertFalse(policy.allowed(True, False, False, 100000))
        policy.reset()
        self.assertEqual(policy.profile, "primary")
        self.assertEqual(policy.failures, 0)
        self.assertTrue(policy.allowed(True, False, False, 100001))

    def test_third_primary_failure_allows_backup_after_backoff(self):
        policy = backend.RetryPolicy(backup_available=True)
        for clock in (0, 15, 45):
            policy.failed(15, clock)
        self.assertEqual(policy.profile, "backup")
        self.assertFalse(policy.exhausted)
        self.assertFalse(policy.allowed(True, False, False, 59))
        self.assertTrue(policy.allowed(True, False, False, 60))

    def test_disabled_and_missing_backup_keep_primary_only(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".deployment") as directory:
            directory = Path(directory)
            settings = directory / "settings.json"
            backup = directory / "backup.txt"
            settings.write_text(json.dumps({"backup_enabled": False}), encoding="utf-8")
            backend.save_credentials(*BACKUP, path=backup)
            with patch.object(profiles, "SETTINGS_PATH", settings), patch.object(profiles, "BACKUP_PATH", backup):
                self.assertEqual(profiles.available_profiles(PRIMARY), [("primary", PRIMARY)])
                self.assertEqual(profiles.backup_credentials(enabled_only=False), BACKUP)
                settings.write_text(json.dumps({"backup_enabled": True}), encoding="utf-8")
                self.assertEqual(profiles.available_profiles(PRIMARY), PROFILES)
                backup.unlink()
                self.assertEqual(profiles.available_profiles(PRIMARY), [("primary", PRIMARY)])

    def test_inspect_accepts_and_labels_backup_account(self):
        client = Mock()
        client.redirect_to_portal.return_value = {"sessionId": "session", "userIp": "10.0.0.1"}
        client.get_online_user_info.return_value = {
            "portalOnlineUserInfo": {"userName": BACKUP[0], "service": BACKUP[2], "redirectUrl": None},
            "onlineUser": {"authenticationTime": "example"},
        }
        with patch.object(backend, "credentials", return_value=PRIMARY), patch.object(
            backend, "available_profiles", return_value=PROFILES
        ):
            state = backend.inspect(client)
        self.assertTrue(state["online"])
        self.assertTrue(state["account_matches"])
        self.assertTrue(state["service_matches"])
        self.assertEqual(state["account_profile"], "backup")
        self.assertNotIn(BACKUP[0], state["account"])

    def test_login_uses_selected_backup_credentials(self):
        client = Mock()
        with patch.object(backend, "make_client", return_value=client), patch.object(
            backend, "inspect", side_effect=[OFFLINE, BACKUP_ONLINE]
        ), patch.object(backend, "backup_credentials", return_value=BACKUP), patch.object(
            backend, "diagnose", return_value=[{"passed": True}]
        ):
            result = backend.network_operation("login", profile="backup")
        client.login.assert_called_once_with(*BACKUP)
        self.assertEqual(result["state"]["account_profile"], "backup")


class BackgroundFailoverTests(unittest.TestCase):
    def run_restore(self, outcome=None, counts=None):
        calls = []
        client = Mock()
        def login(*credentials):
            calls.append(credentials)
            if outcome and credentials == BACKUP:
                client.is_online = True
                return True
            raise RuntimeError(PRIMARY[0] + " " + PRIMARY[1] + " " + BACKUP[0] + " " + BACKUP[1])
        client.login.side_effect = login
        client.is_online = False
        def inspect(*args):
            return dict(BACKUP_ONLINE if client.is_online else OFFLINE)
        report = {"attempt_counts": counts} if counts is not None else {}
        with patch.object(reconnect, "available_profiles", return_value=PROFILES), patch.object(
            reconnect, "make_client", return_value=client
        ), patch.object(reconnect, "check_identity", side_effect=inspect), patch.object(
            reconnect, "internet_check", return_value={"passed": True}
        ), patch.object(reconnect.time, "sleep"):
            success = reconnect.restore_connection(PRIMARY, report, lambda event: None)
        return success, report, calls

    def test_backup_first_attempt_succeeds_after_primary_three(self):
        success, report, calls = self.run_restore(outcome=True)
        self.assertTrue(success)
        self.assertEqual(calls, [PRIMARY] * 3 + [BACKUP])
        self.assertEqual(report["attempt_counts"], {"primary": 3, "backup": 1})
        self.assertEqual(report["after"]["account_profile"], "backup")

    def test_all_failures_stop_after_six_and_do_not_leak_credentials(self):
        success, report, calls = self.run_restore()
        self.assertFalse(success)
        self.assertEqual(calls, [PRIMARY] * 3 + [BACKUP] * 3)
        self.assertEqual(report["attempt_counts"], {"primary": 3, "backup": 3})
        encoded = json.dumps(report)
        for secret in PRIMARY[:2] + BACKUP[:2]:
            self.assertNotIn(secret, encoded)

    def test_guard_resumes_remaining_budget_without_restarting_primary(self):
        success, report, calls = self.run_restore(counts={"primary": 3, "backup": 1})
        self.assertFalse(success)
        self.assertEqual(calls, [BACKUP] * 2)

    def test_guard_does_not_retry_when_both_budgets_are_exhausted(self):
        success, report, calls = self.run_restore(counts={"primary": 3, "backup": 3})
        self.assertFalse(success)
        self.assertEqual(calls, [])


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "Desktop optional dependency not installed")
class DesktopFailoverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from desktop import Window
        self.window = Window(demo=True)
        self.window.timer.stop()
        self.window.schedule_timer.stop()
        self.window.demo = False
        self.window.last_state = None
        self.window.policy = backend.RetryPolicy(backup_available=True)
        self.window.pool = Mock()
        self.window.pool.start.side_effect = lambda task: task.run()
        self.window.add_log = Mock()
        self.window.settings["auto_reconnect"] = True
        self.window.settings["close_to_tray"] = False

    def tearDown(self):
        self.window.pending_close = True
        self.window.tray.hide()
        self.window.close()

    def test_ui_dispatches_three_attempts_to_each_profile_then_stops(self):
        with patch.object(reconnect, "operation_lock", side_effect=contextlib.nullcontext), patch.object(
            backend, "network_operation", side_effect=RuntimeError("test")
        ) as operation:
            for _ in range(7):
                self.window.start("login", automatic=True)
        self.assertEqual([call.kwargs["profile"] for call in operation.call_args_list],
                         ["primary"] * 3 + ["backup"] * 3)
        self.assertTrue(self.window.policy.exhausted)

    def test_ui_stops_switching_as_soon_as_backup_succeeds(self):
        state = {**BACKUP_ONLINE, "account": "bac****ser", "service": BACKUP[2], "ip": "10.0.0.2",
                 "login_time": "example", "checked_at": backend.now()}
        answers = [RuntimeError("primary failed")] * 3 + [{"state": state, "internet": [{"passed": True}]}]
        with patch.object(reconnect, "operation_lock", side_effect=contextlib.nullcontext), patch.object(
            backend, "network_operation", side_effect=answers
        ) as operation:
            for _ in range(4):
                self.window.start("login", automatic=True)
        self.assertEqual([call.kwargs["profile"] for call in operation.call_args_list],
                         ["primary"] * 3 + ["backup"])
        self.assertEqual(self.window.last_state["account_profile"], "backup")
        self.assertEqual(self.window.policy.failures, 0)
        self.assertIn("备用", self.window.hero_description.text())

    def test_manual_logout_disables_both_automatic_modes(self):
        self.window.auto_check.blockSignals(True)
        self.window.auto_check.setChecked(True)
        self.window.auto_check.blockSignals(False)
        self.window.schedule_check.blockSignals(True)
        self.window.schedule_check.setChecked(True)
        self.window.schedule_check.blockSignals(False)
        with patch.object(self.window, "refresh"), patch.object(self.window, "start") as start, patch.object(
            backend, "save_settings"
        ):
            self.window.logout()
        start.assert_called_once_with("logout")
        self.assertFalse(self.window.settings["auto_reconnect"])
        self.assertFalse(self.window.settings["scheduled_reconnect"])
