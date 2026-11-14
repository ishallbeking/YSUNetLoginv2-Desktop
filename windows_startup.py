"""Current-user Windows login startup registration for YSUNet."""
from pathlib import Path
import subprocess
import sys

if sys.platform == "win32":
    import winreg
else:
    winreg = None

ROOT = Path(__file__).resolve().parent
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "YSUNetDesktop"


def startup_command(root=None, executable=None):
    directory = Path(root) if root is not None else ROOT
    pythonw = Path(executable) if executable is not None else Path(sys.executable).with_name("pythonw.exe")
    return subprocess.list2cmdline([str(pythonw.resolve()), str((directory / "desktop.py").resolve()), "--startup"])


def is_enabled():
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            value, kind = winreg.QueryValueEx(key, VALUE_NAME)
            return kind == winreg.REG_SZ and value == startup_command()
    except FileNotFoundError:
        return False


def set_enabled(enabled):
    if winreg is None:
        raise OSError("Windows login startup is only supported on Windows")
    if enabled:
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if not pythonw.is_file() or not (ROOT / "desktop.py").is_file():
            raise FileNotFoundError("Desktop interpreter or source is missing")
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, startup_command())
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, VALUE_NAME)
        except FileNotFoundError:
            pass


def show_initial_window(window, startup=False):
    # If Explorer's tray is not available yet, keep a usable visible window.
    window.background_launch = startup
    if startup and window.tray.isVisible():
        window.hide()
    else:
        window.show()
