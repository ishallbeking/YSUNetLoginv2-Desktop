"""Local launcher: read the existing credential file without copying its secrets."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from functools import partial
import json
from pathlib import Path
import sys

import requests
from ysu_net_login.config import Config, resolve_service_name
from ysu_net_login.ruijie_client import RuijieClient

ROOT = Path(__file__).resolve().parent
DEFAULT_CREDENTIALS = ROOT / "credentials.txt"


def migrate_credentials(path):
    """Rename a legacy local profile lazily, keeping an existing new file."""
    path = Path(path)
    legacy_name = {
        "credentials.txt": "zc.txt",
        "credentials.backup.txt": "zc.backup.txt",
    }.get(path.name)
    if legacy_name and not path.exists():
        legacy = path.with_name(legacy_name)
        try:
            # Windows rename fails if the destination already exists.
            legacy.rename(path)
        except (FileNotFoundError, FileExistsError):
            # Missing legacy files and concurrent migrations are harmless.
            pass
    return path


def read_credentials(path):
    data = migrate_credentials(path).read_bytes()
    encodings = ("utf-16",) if data.startswith((b"\xff\xfe", b"\xfe\xff")) else ("utf-8-sig", "gb18030")
    for encoding in encodings:
        try:
            lines = [line.strip() for line in data.decode(encoding).splitlines() if line.strip()]
            break
        except UnicodeError:
            continue
    else:
        raise ValueError("Cannot decode the credential file.")
    if len(lines) != 3:
        raise ValueError("credentials.txt must contain username, password, and operator on three lines.")
    username, password, operator = lines
    aliases = {"电信": "telecom", "联通": "unicom", "移动": "mobile"}
    service = resolve_service_name(aliases.get(operator, operator), Config())
    return username, password, service


def online_summary(client):
    session_info = client.redirect_to_portal()
    data = client.get_online_user_info(session_info["sessionId"])
    portal = data.get("portalOnlineUserInfo")
    if not isinstance(portal, dict):
        raise ValueError("Unexpected status response from the campus server.")
    online = not bool(portal.get("redirectUrl")) and bool(portal.get("userName") or data.get("onlineUser"))
    return {"online": online, "service": portal.get("service")}, portal.get("userName") or portal.get("userId")


def internet_check(url):
    try:
        with requests.Session() as session:
            session.trust_env = False
            response = session.get(url, timeout=(5, 10))
            expected = (
                response.text.strip() == "Microsoft Connect Test"
                if "msftconnecttest.com" in url
                else "baidu.com" in response.text.lower()
            )
            return {"url": url, "http_status": response.status_code, "passed": response.status_code == 200 and expected}
    except requests.RequestException as error:
        return {"url": url, "passed": False, "error_type": type(error).__name__}


def main():
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="YSU campus network launcher; reads credentials.txt directly.")
    parser.add_argument("command", nargs="?", choices=("login", "status", "verify"), default="login")
    parser.add_argument("--credentials", type=Path, default=DEFAULT_CREDENTIALS)
    args = parser.parse_args()
    report = {"checked_at": datetime.now(timezone(timedelta(hours=8))).isoformat(), "command": args.command}
    secrets = []
    client = RuijieClient(verbose=False)
    client.client.trust_env = False
    client.client.request = partial(client.client.request, timeout=(8, 20))
    try:
        if args.command == "login":
            username, password, service = read_credentials(args.credentials)
            secrets = [username, password]
            report["requested_service"] = service
            report["before"], _ = online_summary(client)
            if report["before"]["online"]:
                report["login_attempted"] = False
            else:
                report["login_attempted"] = True
                report["client_login_success"] = client.login(username, password, service)
            report["after"], online_username = online_summary(client)
            report["account_matches"] = online_username == username
            report["success"] = report["after"]["online"] and report["account_matches"] and report["after"]["service"] == service
        else:
            report["status"], _ = online_summary(client)
            report["success"] = report["status"]["online"]
        if args.command in ("login", "verify"):
            urls = ["http://www.msftconnecttest.com/connecttest.txt", "https://www.baidu.com/"]
            with ThreadPoolExecutor(max_workers=2) as executor:
                report["internet"] = list(executor.map(internet_check, urls))
    except Exception as error:
        message = str(error)
        for secret in secrets:
            message = message.replace(secret, "[REDACTED]")
        report.update(success=False, error_type=type(error).__name__, error=message)
    finally:
        client.client.close()
    (ROOT / ".deployment").mkdir(exist_ok=True)
    output = json.dumps(report, ensure_ascii=False, indent=2)
    (ROOT / ".deployment" / ("last-" + args.command + ".json")).write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
