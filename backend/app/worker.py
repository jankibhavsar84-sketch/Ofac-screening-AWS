"""Compatibility shim for legacy worker entrypoint.

Worker runtime has moved to `worker/worker_app/worker.py`.
"""

from worker_app.worker import run


if __name__ == "__main__":
    run()
