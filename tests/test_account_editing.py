"""Exercise account protection through the Qt controls without real credentials."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import desktop_backend as backend
from desktop import Window


class AccountEditingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        with patch.object(backend, "backup_available", return_value=False):
            self.window = Window(demo=True)
        self.window.timer.stop()
        self.window.schedule_timer.stop()
        self.window.demo = False
        self.window.add_log = Mock()
        self.window.refresh = Mock()
        self.window.settings["close_to_tray"] = False

    def tearDown(self):
        self.window.pending_close = True
        self.window.tray.hide()
        self.window.close()

    def test_both_profiles_start_locked_and_ignore_typing(self):
        for profile in ("primary", "backup"):
            username, password, service, edit, save, cancel = self.window.account_controls(profile)
            for field in (username, password):
                original = field.text()
                QTest.keyClicks(field, "accidental-input")
                self.assertEqual(field.text(), original)
                self.assertTrue(field.isReadOnly())
            self.assertFalse(service.isEnabled())
            self.assertFalse(edit.isHidden())
            self.assertTrue(save.isHidden())
            self.assertTrue(cancel.isHidden())
        self.assertFalse(self.window.delete_backup_button.isEnabled())

    def test_edit_unlocks_only_selected_profile_and_cancel_restores_fields(self):
        for profile in ("primary", "backup"):
            username, password, service, edit, save, cancel = self.window.account_controls(profile)
            before = (username.text(), password.text(), service.currentText())
            QTest.mouseClick(edit, Qt.LeftButton)
            self.assertFalse(username.isReadOnly())
            self.assertFalse(password.isReadOnly())
            self.assertTrue(service.isEnabled())
            other = "backup" if profile == "primary" else "primary"
            self.assertTrue(self.window.account_controls(other)[0].isReadOnly())
            username.setText("edited-user")
            password.setText("edited-password")
            service.setCurrentIndex((service.currentIndex() + 1) % service.count())
            with patch.object(backend, "save_credentials") as save_file:
                QTest.mouseClick(cancel, Qt.LeftButton)
            save_file.assert_not_called()
            self.assertEqual((username.text(), password.text(), service.currentText()), before)
            self.assertTrue(username.isReadOnly())
            self.assertFalse(service.isEnabled())

    def test_save_handlers_cannot_write_without_edit(self):
        with patch.object(backend, "save_credentials") as save_file, patch.object(backend, "save_settings") as settings:
            self.window.save_account()
            self.window.save_backup()
        save_file.assert_not_called()
        settings.assert_not_called()

    def test_successful_saves_relock_both_profiles(self):
        for profile, handler in (("primary", self.window.save_account), ("backup", self.window.save_backup)):
            self.window.begin_account_edit(profile)
            username, password, service, *_ = self.window.account_controls(profile)
            username.setText("test-user")
            password.setText("test-password")
            service.setCurrentText("中国电信")
            with patch.object(backend, "save_credentials") as save_file, patch.object(backend, "save_settings"), patch.object(backend, "backup_available", return_value=True):
                handler()
            save_file.assert_called_once()
            self.assertTrue(username.isReadOnly())
            self.assertFalse(service.isEnabled())
            self.assertNotIn(profile, self.window.account_originals)

    def test_save_failure_keeps_draft_editable_for_both_profiles(self):
        for profile, handler in (("primary", self.window.save_account), ("backup", self.window.save_backup)):
            self.window.begin_account_edit(profile)
            username = self.window.account_controls(profile)[0]
            username.setText("unsaved-user")
            with patch.object(backend, "save_credentials", side_effect=OSError):
                handler()
            self.assertEqual(username.text(), "unsaved-user")
            self.assertFalse(username.isReadOnly())
            self.assertTrue(self.window.account_editing[profile])

    def test_background_busy_state_does_not_unlock_or_discard_drafts(self):
        self.window.begin_account_edit("backup")
        self.window.backup_username.setText("unsaved-backup")
        self.window.set_busy(True)
        self.assertFalse(self.window.backup_username.isEnabled())
        self.assertFalse(self.window.cancel_backup_button.isEnabled())
        self.window.set_busy(False)
        self.assertTrue(self.window.username.isReadOnly())
        self.assertFalse(self.window.service.isEnabled())
        self.assertFalse(self.window.backup_username.isReadOnly())
        self.assertEqual(self.window.backup_username.text(), "unsaved-backup")
        self.window.cycle_path = Path("mock-recovery")
        self.window.set_busy(False)
        self.assertFalse(self.window.edit_account_button.isEnabled())
        self.assertFalse(self.window.save_backup_button.isEnabled())
        self.window.cycle_path = None

    def test_deletion_requires_edit_and_relocks_after_success(self):
        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory) / "credentials.backup.txt"
            backup.write_text("test-user\ntest-password\ntelecom\n", encoding="utf-8")
            with patch.object(backend, "BACKUP_PATH", backup), patch.object(backend, "save_settings"):
                self.window.delete_backup()
                self.assertTrue(backup.exists())
                self.window.begin_account_edit("backup")
                self.assertTrue(self.window.delete_backup_button.isEnabled())
                self.window.delete_backup()
            self.assertFalse(backup.exists())
            self.assertTrue(self.window.backup_username.isReadOnly())
            self.assertFalse(self.window.delete_backup_button.isEnabled())
