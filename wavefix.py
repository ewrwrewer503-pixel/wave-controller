import os
import subprocess
import time
import threading
import shlex
import sys

DEFAULT_EXE_PATH = r"C:\Program Files\Wave\Wave.exe"
DEFAULT_DELAY = 120

state = {
    "exe_path": DEFAULT_EXE_PATH,
    "delay": DEFAULT_DELAY,
    "status": "STOPPED",
}

_loop_thread = None
_stop_flag = threading.Event()


def kill_process(name="Wave.exe"):
    subprocess.run(
        ["taskkill", "/f", "/im", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def launch_process(path):
    try:
        subprocess.Popen(path)
        return True
    except Exception as e:
        print(f"[!] Could not launch: {e}")
        return False


def automation_loop():
    path = state["exe_path"]
    launch_process(path)

    while not _stop_flag.is_set():
        print("[!] Ending task: Wave.exe...")
        kill_process("Wave.exe")
        time.sleep(2)

        if _stop_flag.is_set():
            break

        print("[!] Reopening Wave.exe...")
        launch_process(path)
        time.sleep(1)

        print(f"[!] Waiting {state['delay']}s until next restart...")
        for _ in range(state["delay"]):
            if _stop_flag.is_set():
                break
            time.sleep(1)

    print("[wave] loop exited")


def cmd_start():
    global _loop_thread
    if state["status"] == "RUNNING":
        print("[wave] already running")
        return
    if not os.path.exists(state["exe_path"]):
        print(f"[wave] error: path does not exist -> {state['exe_path']}")
        return
    _stop_flag.clear()
    state["status"] = "RUNNING"
    _loop_thread = threading.Thread(target=automation_loop, daemon=True)
    _loop_thread.start()
    print("[wave] started")


def cmd_stop():
    if state["status"] != "RUNNING":
        print("[wave] not running")
        return
    _stop_flag.set()
    state["status"] = "STOPPED"
    print("[wave] stopping...")


def cmd_status():
    print(f"path  : {state['exe_path']}")
    print(f"delay : {state['delay']}s")
    print(f"status: {state['status']}")


def cmd_set(args):
    if len(args) < 2:
        print("usage: set path <value>  |  set delay <seconds>")
        return
    key, value = args[0].lower(), " ".join(args[1:]).strip('"')
    if key == "path":
        state["exe_path"] = value
        print(f"[wave] path set -> {value}")
    elif key == "delay":
        if value.isdigit():
            state["delay"] = int(value)
            print(f"[wave] delay set -> {value}s")
        else:
            print("[wave] delay must be a number")
    else:
        print(f"[wave] unknown setting '{key}'")


def cmd_help():
    print("Commands:")
    print("  set path <path>   - set path to Wave.exe")
    print("  set delay <secs>  - set restart interval")
    print("  start             - begin restart automation")
    print("  stop              - stop automation")
    print("  status            - show current config/state")
    print("  help              - show this message")
    print("  exit              - quit")


def main():
    print("Wave Controller shell. Type 'help' for commands.")
    while True:
        try:
            raw = input("wave> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            _stop_flag.set()
            sys.exit(0)

        if not raw:
            continue

        try:
            parts = shlex.split(raw)
        except ValueError as e:
            print(f"[wave] parse error: {e}")
            continue

        cmd, args = parts[0].lower(), parts[1:]

        if cmd == "start":
            cmd_start()
        elif cmd == "stop":
            cmd_stop()
        elif cmd == "status":
            cmd_status()
        elif cmd == "set":
            cmd_set(args)
        elif cmd in ("help", "?"):
            cmd_help()
        elif cmd in ("exit", "quit", "q"):
            _stop_flag.set()
            break
        else:
            print(f"[wave] unknown command '{cmd}' (try 'help')")


if __name__ == "__main__":
    main()
