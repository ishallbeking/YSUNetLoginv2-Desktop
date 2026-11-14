"""Run a campus logout/relogin test independently of the Codex connection."""
import argparse
import ctypes
from contextlib import contextmanager
import msvcrt
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from local_client import read_credentials, online_summary, internet_check
from account_profiles import available_profiles
from ysu_net_login.ruijie_client import RuijieClient
from functools import partial

URLS = ["http://www.msftconnecttest.com/connecttest.txt", "https://www.baidu.com/"]


def timestamp():
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def make_client():
    client = RuijieClient(verbose=False)
    client.client.trust_env = False
    client.client.request = partial(client.client.request, timeout=(6, 15))
    return client


def clean_error(error, credentials):
    # Server responses can echo credentials or tickets from either profile.
    return {"error_type": type(error).__name__, "error": "Connection or authentication operation failed."}


def write_json(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def publish(directory, report, event):
    report["updated_at"] = timestamp()
    with (directory / "events.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"at": report["updated_at"], "event": event}, ensure_ascii=False) + "\n")
    write_json(directory / "result.json", report)
    write_json(ROOT / ".deployment" / "last-reconnect.json", report)


def check_identity(client, credentials):
    state, username = online_summary(client)
    profiles = available_profiles(credentials)
    matched = next(((name, values) for name, values in profiles
                    if username == values[0] and state["service"] == values[2]), None)
    state["account_matches"] = any(username == values[0] for _, values in profiles)
    state["service_matches"] = bool(matched)
    state["account_profile"] = matched[0] if matched else None
    return state


def expected_online(state):
    return state["online"] and state["account_matches"] and state["service_matches"]


@contextmanager
def operation_lock():
    (ROOT / ".deployment").mkdir(exist_ok=True)
    with (ROOT / ".deployment" / "reconnect.lock").open("a+b") as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def instrument_authentication(client, report, emit):
    original_cas = client.cas_sso_login
    original_service = client.service_login
    def cas_login(*args, **kwargs):
        report["cas_login_attempted"] = True
        emit("project_cas_login_start")
        result = original_cas(*args, **kwargs)
        report["cas_login_success"] = bool(result)
        emit("project_cas_login_finished")
        return result
    def service_login(*args, **kwargs):
        report["service_login_attempted"] = True
        emit("project_service_login_start")
        result = original_service(*args, **kwargs)
        report["service_auth_result"] = (result.get("data") or {}).get("authResult")
        emit("project_service_login_finished")
        return result
    client.cas_sso_login = cas_login
    client.service_login = service_login


def restore_connection(credentials, report, emit, attempts=3):
    profiles = available_profiles(credentials)
    counts = report.setdefault("attempt_counts", {"primary": 0, "backup": 0})
    # A guardian may resume after the worker logged in but before it recorded
    # success. Verify the existing connection before consuming another attempt.
    if any(counts.values()):
        check = make_client()
        try:
            state = check_identity(check, credentials)
            if expected_online(state):
                internet = [internet_check(url) for url in URLS]
                if all(item["passed"] for item in internet):
                    report.update(after=state, internet=internet, restored=True)
                    emit("connection_restored")
                    return True
        except Exception:
            pass
        finally:
            check.client.close()
    for profile, selected in profiles:
        if profile == "backup" and counts.get("primary", 0) >= attempts:
            emit("switch_to_backup_account")
        for attempt in range(counts.get(profile, 0) + 1, attempts + 1):
            counts[profile] = attempt
            entry = {"attempt": attempt, "account_profile": profile}
            report.setdefault("reconnect_attempts", []).append(entry)
            # Persist the budget before performing requests, so a crashed
            # worker cannot restart the same three attempts in the guardian.
            emit("reconnect_attempt")
            client = make_client()
            instrument_authentication(client, report, emit)
            try:
                entry["before"] = check_identity(client, credentials)
                if entry["before"]["online"] and not expected_online(entry["before"]):
                    raise RuntimeError("An unrelated account is already online")
                if not expected_online(entry["before"]):
                    report["login_attempted"] = True
                    emit("project_login_start")
                    try:
                        entry["client_login_success"] = client.login(*selected)
                    except Exception as error:
                        entry.update(clean_error(error, selected))
                entry["after"] = check_identity(client, credentials)
                if expected_online(entry["after"]):
                    entry["internet"] = [internet_check(url) for url in URLS]
                    if all(item["passed"] for item in entry["internet"]):
                        report["after"] = entry["after"]
                        report["internet"] = entry["internet"]
                        report["restored"] = True
                        emit("connection_restored")
                        return True
            except Exception as error:
                entry.update(clean_error(error, selected))
            finally:
                client.client.close()
            emit("reconnect_attempt_failed")
            if attempt < attempts:
                time.sleep(attempt * 3)
    report["restored"] = False
    return False


def observe_offline(credentials):
    observations = []
    for _ in range(5):
        client = make_client()
        try:
            state = check_identity(client, credentials)
            observations.append({"checked_at": timestamp(), **state})
            if not state["online"]:
                return True, observations
        finally:
            client.client.close()
        time.sleep(1)
    return False, observations


def cycle(credentials, report, emit):
    client = make_client()
    try:
        report["phase"] = "disconnecting"
        report["logout_started"] = True
        emit("project_logout_start")
        report["client_logout_success"] = client.logout()
        report["offline_observed"], report["offline_observations"] = observe_offline(credentials)
        emit("logout_checked")
        if report["offline_observed"]:
            report["offline_internet"] = [internet_check(URLS[0])]
            emit("offline_internet_checked")
    except Exception as error:
        report["logout_error"] = clean_error(error, credentials)
        emit("logout_error")
    finally:
        client.client.close()
        report["phase"] = "reconnecting"
        emit("automatic_reconnect_start")
        restored = restore_connection(credentials, report, emit)
    report["success"] = bool(restored and report.get("offline_observed") and report.get("cas_login_success"))
    report["phase"] = "completed" if restored else "failed"
    emit("test_finished")
    return report["success"]


def spawn_background(arguments, directory, label):
    with (directory / (label + ".log")).open("ab", buffering=0) as output:
        return subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), *arguments],
            cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=output, stderr=output,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
            close_fds=True,
        )


def guard(directory, worker_pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.TerminateProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x100000 | 0x0001, False, worker_pid)
    if not handle:
        raise OSError("Cannot monitor reconnect worker.")
    write_json(directory / "guard-ready.json", {"pid": __import__("os").getpid(), "ready": True})
    deadline = time.monotonic() + 360
    report = {}
    try:
        while time.monotonic() < deadline:
            try:
                report = json.loads((directory / "result.json").read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                pass
            if report.get("restored") and report.get("phase") == "completed":
                write_json(directory / "guard-result.json", {"recovery_needed": False, "finished_at": timestamp()})
                return 0
            if report.get("phase") == "failed" or kernel.WaitForSingleObject(handle, 0) != 258:
                break
            time.sleep(1)
        if not report.get("logout_started"):
            write_json(directory / "guard-result.json", {"recovery_needed": False, "reason": "logout_not_started"})
            return 0
        if kernel.WaitForSingleObject(handle, 0) == 258:
            if not kernel.TerminateProcess(handle, 1):
                raise OSError("Cannot stop stalled reconnect worker.")
            kernel.WaitForSingleObject(handle, 5000)
        credentials = read_credentials(ROOT / "zc.txt")
        report["phase"] = "guard_recovery"
        report["guard_recovery"] = True
        emit = lambda event: publish(directory, report, event)
        emit("independent_guard_recovery_start")
        restored = restore_connection(credentials, report, emit)
        report["success"] = bool(restored and report.get("offline_observed") and report.get("cas_login_success"))
        report["phase"] = "completed" if restored else "failed"
        emit("independent_guard_recovery_finished")
        write_json(directory / "guard-result.json", {"recovery_needed": True, "restored": restored, "finished_at": timestamp()})
        return 0 if restored else 1
    finally:
        kernel.CloseHandle(handle)


def preflight():
    credentials = read_credentials(ROOT / "zc.txt")
    client = make_client()
    try:
        state = check_identity(client, credentials)
        if not expected_online(state):
            raise RuntimeError("Preflight requires the expected account and service to be online.")
        return credentials, state
    finally:
        client.client.close()


def worker(directory, dry_run):
    credentials, state = preflight()
    report = {"started_at": timestamp(), "run_directory": str(directory), "before": state,
              "phase": "prepared", "dry_run": dry_run, "success": False, "restored": False}
    emit = lambda event: publish(directory, report, event)
    emit("preflight_passed")
    if dry_run:
        report.update(phase="dry_run_completed", success=True, logout_started=False)
        emit("dry_run_passed_no_logout")
        return 0
    guardian = spawn_background(["--guard", str(directory), "--worker-pid", str(__import__("os").getpid())], directory, "guard")
    report["guard_pid"] = guardian.pid
    for _ in range(50):
        if (directory / "guard-ready.json").exists():
            break
        if guardian.poll() is not None:
            raise RuntimeError("Recovery guard exited before becoming ready; logout cancelled.")
        time.sleep(0.1)
    else:
        guardian.terminate()
        raise RuntimeError("Recovery guard did not become ready; logout cancelled.")
    emit("independent_guard_ready")
    return 0 if cycle(credentials, report, emit) else 1


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Detached campus logout/relogin test with independent recovery guard.")
    parser.add_argument("--dry-run", action="store_true", help="Validate background execution without disconnecting.")
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--guard", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--worker-pid", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.guard:
        return guard(args.guard, args.worker_pid)
    if args.worker:
        with operation_lock():
            return worker(args.worker, args.dry_run)
    preflight()
    (ROOT / ".deployment").mkdir(exist_ok=True)
    directory = ROOT / ".deployment" / ("reconnect-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6])
    directory.mkdir()
    arguments = ["--worker", str(directory)]
    if args.dry_run:
        arguments.append("--dry-run")
    process = spawn_background(arguments, directory, "worker")
    print(json.dumps({"started": True, "worker_pid": process.pid, "dry_run": args.dry_run, "result": str(directory / "result.json")}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        # Do not write raw server responses or credentials to the process log.
        print(json.dumps({"fatal_error_type": type(error).__name__}))
        sys.exit(1)
