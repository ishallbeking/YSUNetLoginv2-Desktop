"""Network operations and persistent settings for the desktop client."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from functools import partial
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from local_client import read_credentials, internet_check
from ysu_net_login.ruijie_client import RuijieClient

STATE = ROOT / ".deployment"
SETTINGS = STATE / "desktop-settings.json"
LOG = STATE / "desktop-events.jsonl"
SERVICES = ["校园网", "中国电信", "中国联通", "中国移动"]
URLS = ["http://www.msftconnecttest.com/connecttest.txt", "https://www.baidu.com/"]


def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def mask_account(username):
    return username[:3] + "****" + username[-3:] if len(username) > 6 else "****"


def load_settings():
    defaults = {"auto_reconnect": False, "interval": 30, "close_to_tray": False, "scheduled_reconnect": False, "schedule_minutes": 60}
    try:
        data = json.loads(SETTINGS.read_text(encoding="utf-8"))
        defaults.update({key: value for key, value in data.items() if key in defaults})
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    for key, lower, upper, fallback in (("interval", 15, 300, 30), ("schedule_minutes", 5, 1440, 60)):
        try:
            defaults[key] = max(lower, min(upper, int(defaults[key])))
        except (ValueError, TypeError, OverflowError):
            defaults[key] = fallback
    defaults["scheduled_reconnect"] = defaults["scheduled_reconnect"] is True
    defaults["auto_reconnect"] = defaults["auto_reconnect"] is True
    defaults["close_to_tray"] = defaults["close_to_tray"] is True
    return defaults


def save_settings(settings):
    STATE.mkdir(exist_ok=True)
    temporary = SETTINGS.with_suffix(".tmp")
    temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(SETTINGS)


def save_credentials(username, password, service, path=None):
    destination = path or ROOT / "zc.txt"
    if not username or not password or service not in SERVICES:
        raise ValueError("请输入完整账号、密码并选择运营商。")
    if any("\n" in value or "\r" in value for value in (username, password, service)):
        raise ValueError("账号和密码不能包含换行。")
    temporary = destination.with_suffix(".tmp")
    try:
        temporary.write_text("\n".join((username.strip(), password, service)) + "\n", encoding="utf-8")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def credentials():
    return read_credentials(ROOT / "zc.txt")


def error_message(error):
    # Fixed messages ensure server errors can never echo credentials or tickets.
    import requests
    if isinstance(error, requests.Timeout):
        return "认证服务器响应超时，请检查校园网连接后重试。"
    if isinstance(error, requests.ConnectionError):
        return "无法连接认证服务器，请确认已连接校园网。"
    if isinstance(error, FileNotFoundError):
        return "未找到 zc.txt，请先在账号设置中保存账号。"
    if isinstance(error, ValueError):
        return "账号配置或服务器响应有误，请检查设置。"
    return "操作未完成，请核对账号密码、运营商及校园网连接。"


def make_client():
    client = RuijieClient(verbose=False)
    client.client.trust_env = False
    client.client.request = partial(client.client.request, timeout=(5, 12))
    return client


def inspect(client):
    session = client.redirect_to_portal()
    data = client.get_online_user_info(session["sessionId"])
    portal = data.get("portalOnlineUserInfo")
    if not isinstance(portal, dict):
        raise ValueError("Unexpected portal status")
    user = portal.get("userName") or portal.get("userId") or ""
    online = not bool(portal.get("redirectUrl")) and bool(user or data.get("onlineUser"))
    try:
        configured, _, service = credentials()
    except (OSError, ValueError):
        configured, service = "", ""
    return {
        "online": online, "service": portal.get("service") or service or "未配置",
        "account": mask_account(configured) if configured else "未配置",
        "account_matches": bool(user and configured == user) if online else None,
        "service_matches": portal.get("service") == service if online else None,
        "ip": portal.get("userIp") or session.get("userIp") or "—",
        "login_time": (data.get("onlineUser") or {}).get("authenticationTime") or "—",
        "checked_at": now(),
    }


def diagnose():
    with ThreadPoolExecutor(max_workers=2) as executor:
        return list(executor.map(internet_check, URLS))


def network_operation(action):
    client = make_client()
    try:
        state = inspect(client)
        if action == "login":
            username, password, service = credentials()
            if state["online"]:
                if not state["account_matches"] or not state["service_matches"]:
                    raise RuntimeError("Already online using another account or service")
            else:
                client.login(username, password, service)
                state = inspect(client)
            if not state["online"] or not state["account_matches"] or not state["service_matches"]:
                raise RuntimeError("Login state mismatch")
        elif action == "logout":
            client.logout()
            for attempt in range(4):
                state = inspect(client)
                if not state["online"]:
                    break
                time.sleep(0.6)
            if state["online"]:
                raise RuntimeError("Logout did not complete")
        result = {"action": action, "state": state}
        if action in ("diagnose", "login"):
            result["internet"] = diagnose()
        return result
    finally:
        client.client.close()


def log_event(message, level="info"):
    STATE.mkdir(exist_ok=True)
    item = {"time": now(), "level": level, "message": message}
    lines = []
    if LOG.exists():
        lines = LOG.read_text(encoding="utf-8").splitlines()[-399:]
    lines.append(json.dumps(item, ensure_ascii=False))
    temporary = LOG.with_suffix(".tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary.replace(LOG)
    return item


def load_events():
    try:
        return [json.loads(line) for line in LOG.read_text(encoding="utf-8").splitlines() if line.strip()][-200:]
    except (OSError, ValueError):
        return []


class RetryPolicy:
    """Bound retries and never confuse an unavailable status query with offline."""
    def __init__(self):
        self.failures = 0
        self.next_attempt = 0.0

    def allowed(self, enabled, online, busy, clock=None):
        clock = time.monotonic() if clock is None else clock
        return enabled and online is False and not busy and self.failures < 3 and clock >= self.next_attempt

    def failed(self, interval, clock=None):
        clock = time.monotonic() if clock is None else clock
        self.failures += 1
        self.next_attempt = clock + min(300, interval * (2 ** (self.failures - 1)))

    def reset(self):
        self.failures = 0
        self.next_attempt = 0.0
