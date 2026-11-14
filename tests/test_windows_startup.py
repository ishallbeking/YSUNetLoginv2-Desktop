import ctypes
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, Mock, patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import windows_startup as startup


class StartupTests(unittest.TestCase):
    def test_command_quotes_paths_and_has_no_credentials(self):
        directory = ROOT / "directory with spaces"
        executable = ROOT / ".runtime" / "pythonw.exe"
        command = startup.startup_command(directory, executable)
        count = ctypes.c_int()
        parse = ctypes.windll.shell32.CommandLineToArgvW
        parse.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
        parse.restype = ctypes.POINTER(ctypes.c_wchar_p)
        args = parse(command, ctypes.byref(count))
        try:
            self.assertEqual([args[index] for index in range(count.value)], [
                str(executable.resolve()), str((directory / "desktop.py").resolve()), "--startup",
            ])
        finally:
            free = ctypes.windll.kernel32.LocalFree
            free.argtypes = [ctypes.c_void_p]
            free(ctypes.cast(args, ctypes.c_void_p))
        self.assertNotIn("credentials.txt", command)
        self.assertNotIn("password", command)

    def test_registration_round_trip_in_isolated_non_startup_key(self):
        registry = startup.winreg
        key_path = "Software\\YSUNetDesktopStartupTest_" + uuid.uuid4().hex
        try:
            with patch.object(startup, "RUN_KEY", key_path):
                self.assertFalse(startup.is_enabled())
                startup.set_enabled(True)
                self.assertTrue(startup.is_enabled())
                with registry.OpenKey(registry.HKEY_CURRENT_USER, key_path, 0, registry.KEY_SET_VALUE) as key:
                    registry.SetValueEx(key, "UnrelatedValue", 0, registry.REG_SZ, "keep")
                startup.set_enabled(False)
                self.assertFalse(startup.is_enabled())
                with registry.OpenKey(registry.HKEY_CURRENT_USER, key_path) as key:
                    self.assertEqual(registry.QueryValueEx(key, "UnrelatedValue")[0], "keep")
                startup.set_enabled(False)
        finally:
            try:
                registry.DeleteKey(registry.HKEY_CURRENT_USER, key_path)
            except FileNotFoundError:
                pass

    def test_stale_registration_does_not_claim_current_directory_enabled(self):
        registry = MagicMock()
        registry.HKEY_CURRENT_USER = 1
        registry.KEY_READ = 2
        registry.REG_SZ = 1
        registry.QueryValueEx.return_value = ("old command", 1)
        with patch.object(startup, "winreg", registry):
            self.assertFalse(startup.is_enabled())

    def test_startup_uses_tray_when_available(self):
        window = Mock()
        window.tray.isVisible.return_value = True
        startup.show_initial_window(window, startup=True)
        window.hide.assert_called_once()
        window.show.assert_not_called()

    def test_startup_keeps_window_visible_without_tray(self):
        window = Mock()
        window.tray.isVisible.return_value = False
        startup.show_initial_window(window, startup=True)
        window.show.assert_called_once()
        window.hide.assert_not_called()

    def test_manual_launch_shows_main_window(self):
        window = Mock()
        startup.show_initial_window(window, startup=False)
        window.show.assert_called_once()
        self.assertFalse(window.background_launch)


class StartupUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from desktop import Window
        self.window = Window(demo=True)
        self.window.timer.stop()
        self.window.schedule_timer.stop()
        self.window.demo = False
        self.window.settings["close_to_tray"] = False
        self.window.add_log = Mock()

    def tearDown(self):
        self.window.pending_close = True
        self.window.tray.hide()
        self.window.close()

    def test_ui_enables_and_disables_registration(self):
        with patch.object(startup, "set_enabled") as change:
            self.window.startup_check.setChecked(True)
            self.window.startup_check.setChecked(False)
        self.assertEqual([call.args[0] for call in change.call_args_list], [True, False])

    def test_permission_error_restores_checkbox(self):
        with patch.object(startup, "set_enabled", side_effect=PermissionError):
            self.window.startup_check.setChecked(True)
        self.assertFalse(self.window.startup_check.isChecked())
        self.assertIn("无法修改", self.window.notice.text())
