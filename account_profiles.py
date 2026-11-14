"""Local primary/backup profiles shared by the UI and recovery worker."""
import json
from pathlib import Path

from local_client import read_credentials

ROOT = Path(__file__).resolve().parent
BACKUP_PATH = ROOT / "credentials.backup.txt"
SETTINGS_PATH = ROOT / ".deployment" / "desktop-settings.json"


def backup_credentials(enabled_only=True):
    if enabled_only:
        try:
            settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if settings.get("backup_enabled") is not True:
                return None
        except (OSError, ValueError, AttributeError):
            return None
    try:
        return read_credentials(BACKUP_PATH)
    except FileNotFoundError:
        return None


def available_profiles(primary=None):
    primary = primary if primary is not None else read_credentials(ROOT / "credentials.txt")
    result = [("primary", primary)]
    try:
        backup = backup_credentials()
    except (OSError, ValueError):
        backup = None
    if backup and backup != primary:
        result.append(("backup", backup))
    return result


def backup_available():
    try:
        return len(available_profiles()) == 2
    except (OSError, ValueError):
        return False
