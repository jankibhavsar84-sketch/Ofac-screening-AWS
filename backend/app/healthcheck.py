from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

from .config import settings


def _check_backend() -> None:
    url = os.getenv("BACKEND_HEALTHCHECK_URL", "http://127.0.0.1:8000/health").strip() or "http://127.0.0.1:8000/health"
    timeout_s = float(os.getenv("BACKEND_HEALTHCHECK_TIMEOUT_S", "5"))

    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as response:
            status_code = int(getattr(response, "status", 0))
            body = response.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"backend health URL unreachable: {exc}") from exc

    if status_code != 200:
        raise RuntimeError(f"backend health endpoint returned HTTP {status_code}")
    if not body:
        return

    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return

    if isinstance(payload, dict) and str(payload.get("status") or "").strip().lower() == "ok":
        return
    raise RuntimeError("backend health payload did not include status=ok")


def _check_worker() -> None:
    path = (os.getenv("WORKER_HEARTBEAT_PATH") or settings.worker_heartbeat_path).strip()
    max_age_s = int(os.getenv("WORKER_HEALTH_MAX_AGE_S", str(settings.worker_health_max_age_s)))
    if not path:
        raise RuntimeError("WORKER_HEARTBEAT_PATH is empty")
    if max_age_s <= 0:
        raise RuntimeError("WORKER_HEALTH_MAX_AGE_S must be > 0")

    heartbeat_file = Path(path)
    if not heartbeat_file.exists():
        raise RuntimeError(f"worker heartbeat file not found: {heartbeat_file}")

    try:
        raw = heartbeat_file.read_text(encoding="ascii").strip()
        heartbeat_epoch = float(raw)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"invalid worker heartbeat file: {heartbeat_file}") from exc

    age_s = time.time() - heartbeat_epoch
    if age_s > max_age_s:
        raise RuntimeError(
            f"worker heartbeat stale: age={age_s:.1f}s max={max_age_s}s file={heartbeat_file}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Container health checks for backend and worker.")
    parser.add_argument("target", choices=["backend", "worker"])
    args = parser.parse_args(argv)

    try:
        if args.target == "backend":
            _check_backend()
        else:
            _check_worker()
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
