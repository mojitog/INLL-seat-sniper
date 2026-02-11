import argparse
import json
import subprocess
import sys
import time
from typing import List, Dict

import requests


CHECK_SCRIPT = "availability-check.py"
DEFAULT_INTERVAL = 60


def run_check() -> List[Dict[str, str]]:
    try:
        result = subprocess.run(
            [sys.executable, CHECK_SCRIPT, "--format", "json"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"[warn] check failed: {exc}")
        return []
    try:
        return json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        print(f"[warn] invalid JSON from checker: {exc}")
        return []


def handle_available(sessions: List[Dict[str, str]]) -> None:
    topic = "INLL-free-spot-checker-mo"
    url = f"https://ntfy.sh/{topic}"
    lines = ["Available sessions detected:"]
    for s in sessions:
        lines.append(f"{s.get('reference')} | {s.get('availability')}")
    body = "\n".join(lines)

    try:
        resp = requests.post(url, data=body.encode("utf-8"), timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[warn] ntfy send failed: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Watch INLL availability and send ntfy alerts.")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL, help="Polling interval in seconds")
    parser.add_argument("--once", action="store_true", help="Run a single check and exit")
    args = parser.parse_args()

    while True:
        try:
            sessions = run_check()
            available = [s for s in sessions if s.get("availability") == "available"]
            if available:
                handle_available(available)
        except Exception as exc:
            print(f"[warn] unexpected error: {exc}")
        if args.once:
            return
        time.sleep(max(10, args.interval))


if __name__ == "__main__":
    main()
