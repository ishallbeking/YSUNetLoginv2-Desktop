"""Credential filename upgrades preserve local secrets and existing settings."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from local_client import migrate_credentials, read_credentials
import desktop_backend as backend


class CredentialMigrationTests(unittest.TestCase):
    def test_primary_and_backup_preserve_original_bytes_and_encoding(self):
        for name, legacy in [("credentials.txt", "zc.txt"),
                             ("credentials.backup.txt", "zc.backup.txt")]:
            for encoding in ("utf-8-sig", "utf-16", "gb18030"):
                with self.subTest(name=name, encoding=encoding), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    old, new = root / legacy, root / name
                    original = "test-account\r\ntest-password\r\n中国电信\r\n".encode(encoding)
                    old.write_bytes(original)
                    self.assertEqual(read_credentials(new), ("test-account", "test-password", "中国电信"))
                    self.assertFalse(old.exists())
                    self.assertEqual(new.read_bytes(), original)
                    migrate_credentials(new)
                    self.assertEqual(new.read_bytes(), original)

    def test_existing_new_config_takes_priority_and_preserves_both(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old, new = root / "zc.txt", root / "credentials.txt"
            old.write_bytes(b"old-user\nold-password\ntelecom\n")
            new.write_bytes(b"new-user\nnew-password\ntelecom\n")
            before = (old.read_bytes(), new.read_bytes())
            self.assertEqual(read_credentials(new)[0], "new-user")
            self.assertEqual((old.read_bytes(), new.read_bytes()), before)

    def test_missing_profile_is_not_created(self):
        with tempfile.TemporaryDirectory() as directory:
            new = Path(directory) / "credentials.txt"
            with self.assertRaises(FileNotFoundError):
                read_credentials(new)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_custom_path_does_not_consume_legacy_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / "zc.txt"
            old.write_bytes(b"old-user\nold-password\ntelecom\n")
            with self.assertRaises(FileNotFoundError):
                read_credentials(root / "custom.txt")
            self.assertTrue(old.exists())

    def test_save_upgrades_legacy_before_writing_new_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old, new = root / "zc.txt", root / "credentials.txt"
            old.write_bytes(b"old-user\nold-password\ntelecom\n")
            backend.save_credentials("new-user", "new-password", "中国电信", new)
            self.assertFalse(old.exists())
            self.assertEqual(read_credentials(new), ("new-user", "new-password", "中国电信"))
            self.assertFalse(new.with_suffix(".tmp").exists())
