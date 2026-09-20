import json
import os
import signal
import subprocess
import sys
import time
from typing import Optional, Dict, Any


BASE_DIR = os.path.dirname(__file__)
PID_FILE = os.path.join(BASE_DIR, "offline_receiver_state.json")
LOG_FILE = os.path.join(BASE_DIR, "offline_receiver.log")
RECEIVER_SCRIPT = os.path.join(BASE_DIR, "offline_bluetooth_receiver.py")

# Prefer the backend venv python if it exists, otherwise fall back to current interpreter.
VENV_PYTHON = os.path.join(BASE_DIR, "venv311", "Scripts", "python.exe")
PYTHON_EXE = VENV_PYTHON if os.path.exists(VENV_PYTHON) else sys.executable


def _read_state() -> Dict[str, Any]:
    if not os.path.exists(PID_FILE):
        return {}
    try:
        with open(PID_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_state(data: Dict[str, Any]) -> None:
    with open(PID_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _clear_state() -> None:
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except Exception:
        pass


def _is_pid_running(pid: Optional[int]) -> bool:
    if not pid:
        return False

    try:
        if os.name == "nt":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return str(pid) in result.stdout
        else:
            os.kill(pid, 0)
            return True
    except Exception:
        return False


def get_receiver_status() -> Dict[str, Any]:
    state = _read_state()
    pid = state.get("pid")
    merchant_username = state.get("merchant_username")

    running = _is_pid_running(pid)
    if not running and state:
        _clear_state()

    return {
        "running": running,
        "pid": pid if running else None,
        "merchant_username": merchant_username if running else None,
        "script": RECEIVER_SCRIPT,
        "python_exe": PYTHON_EXE,
        "log_file": LOG_FILE,
    }


def start_receiver(merchant_username: str) -> Dict[str, Any]:
    current = get_receiver_status()
    if current["running"]:
        return {
            "ok": True,
            "message": "Receiver already running",
            "pid": current["pid"],
            "merchant_username": current["merchant_username"],
        }

    if not os.path.exists(RECEIVER_SCRIPT):
        return {
            "ok": False,
            "message": f"Receiver script not found: {RECEIVER_SCRIPT}",
        }

    try:
        log_handle = open(LOG_FILE, "a", encoding="utf-8")
        log_handle.write("\n===== START RECEIVER =====\n")
        log_handle.write(f"python_exe={PYTHON_EXE}\n")
        log_handle.write(f"receiver_script={RECEIVER_SCRIPT}\n")
        log_handle.flush()

        env = os.environ.copy()
        env["RECEIVER_MERCHANT_USERNAME"] = merchant_username

        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            proc = subprocess.Popen(
                [PYTHON_EXE, RECEIVER_SCRIPT],
                cwd=BASE_DIR,
                creationflags=creationflags,
                stdout=log_handle,
                stderr=log_handle,
                stdin=subprocess.DEVNULL,
                env=env,
            )
        else:
            proc = subprocess.Popen(
                [PYTHON_EXE, RECEIVER_SCRIPT],
                cwd=BASE_DIR,
                stdout=log_handle,
                stderr=log_handle,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                env=env,
            )

        _write_state({
            "pid": proc.pid,
            "merchant_username": merchant_username,
        })

        # Give the receiver a moment to start and crash if it's going to fail immediately.
        time.sleep(2)

        if not _is_pid_running(proc.pid):
            return {
                "ok": False,
                "message": f"Receiver exited immediately. Check log: {LOG_FILE}",
                "pid": proc.pid,
                "merchant_username": merchant_username,
            }

        return {
            "ok": True,
            "message": "Receiver started",
            "pid": proc.pid,
            "merchant_username": merchant_username,
        }

    except Exception as e:
        return {
            "ok": False,
            "message": f"Could not start receiver: {e}",
        }


def stop_receiver() -> Dict[str, Any]:
    state = _read_state()
    pid = state.get("pid")

    if not pid:
        _clear_state()
        return {
            "ok": True,
            "message": "Receiver already stopped",
        }

    if not _is_pid_running(pid):
        _clear_state()
        return {
            "ok": True,
            "message": "Receiver already not running",
        }

    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                capture_output=True,
                text=True,
                timeout=10
            )
        else:
            os.kill(pid, signal.SIGTERM)

        _clear_state()

        return {
            "ok": True,
            "message": "Receiver stopped",
            "pid": pid,
        }

    except Exception as e:
        return {
            "ok": False,
            "message": f"Could not stop receiver: {e}",
            "pid": pid,
        }