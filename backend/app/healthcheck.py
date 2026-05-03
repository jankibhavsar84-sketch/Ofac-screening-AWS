from __future__ import annotations

import argparse
import json
import os
import sys
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
    host = (os.getenv("WORKER_HEALTH_HOST") or settings.worker_health_host).strip() or "127.0.0.1"
    port = int(os.getenv("WORKER_HEALTH_PORT", str(settings.worker_health_port)))
    timeout_s = float(os.getenv("WORKER_HEALTHCHECK_TIMEOUT_S", str(settings.worker_healthcheck_timeout_s)))
    url = os.getenv("WORKER_HEALTHCHECK_URL", "").strip() or f"http://{host}:{port}/health"

    if port <= 0:
        raise RuntimeError("WORKER_HEALTH_PORT must be > 0")
    if timeout_s <= 0:
        raise RuntimeError("WORKER_HEALTHCHECK_TIMEOUT_S must be > 0")

    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as response:
            status_code = int(getattr(response, "status", 0))
            body = response.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"worker health URL unreachable: {exc}") from exc

    if status_code != 200:
        detail = body.decode("utf-8", errors="replace").strip() if body else ""
        suffix = f" body={detail}" if detail else ""
        raise RuntimeError(f"worker health endpoint returned HTTP {status_code}{suffix}")

    if not body:
        return
    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return
    if isinstance(payload, dict) and str(payload.get("status") or "").strip().lower() == "ok":
        return
    raise RuntimeError("worker health payload did not include status=ok")


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
