"""Local Celery supervisor. Windows solo is for development, Linux prefork for production."""
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime

from sqlalchemy import text

from stock_agents.common.config import load_settings, project_root
from stock_agents.jobs.queue import sync_engine


def main():
    load_settings()
    root = project_root()
    logs = root / "logs"
    logs.mkdir(exist_ok=True)
    pool = "solo" if os.name == "nt" else "prefork"
    base = [sys.executable, "-m", "celery", "-A", "stock_agents.jobs.celery_app:app"]
    commands = {
        "pipeline-worker": ["worker", "-Q", "quantora-pipelines", "-n", "pipeline@%h", "--pool", pool, "-c", "1", "-l", "INFO"],
        "pipeline-control": ["worker", "-Q", "quantora-control", "-n", "control@%h", "--pool", pool, "-c", "1", "-l", "INFO"],
        "pipeline-beat": ["beat", "-s", str(logs / "celerybeat-schedule"), "-l", "INFO"],
    }
    children, handles = {}, {}
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with sync_engine().connect() as lock:
        if not lock.scalar(text("SELECT pg_try_advisory_lock(490122883)")):
            return
        lock.commit()
        try:
            while not stopping:
                # The connection lock prevents duplicate supervisors, including scheduled restarts.
                lock.execute(text("SELECT 1"))
                lock.commit()
                if os.name == "nt":
                    # Solo has no Celery hard-limit support. Bound a hung stage locally.
                    stages = lock.execute(text("SELECT stages FROM pipeline_runs WHERE status='running'")).scalars().all()
                    lock.commit()
                    overdue = any(stage.get("status") == "running" and
                        (datetime.now(UTC)-datetime.fromisoformat(stage["started_at"])).total_seconds() > 7200
                        for run in stages for stage in run)
                    child = children.get("pipeline-worker")
                    if overdue and child and child.poll() is None:
                        child.kill()
                        child.wait(15)
                        # Stale heartbeat reconciliation safely resumes committed stages.
                        lock.execute(text("UPDATE pipeline_runs SET heartbeat_at=NULL,status='retrying',next_attempt_at=now() WHERE status='running'"))
                        lock.commit()
                for name, args in commands.items():
                    child = children.get(name)
                    if child is None or child.poll() is not None:
                        if name in handles:
                            handles[name].close()
                        handles[name] = (logs / (name + ".log")).open("a", encoding="utf-8")
                        children[name] = subprocess.Popen(base + args, cwd=root, stdout=handles[name], stderr=subprocess.STDOUT,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                time.sleep(5)
        finally:
            for child in children.values():
                if child.poll() is None:
                    child.terminate()
            for child in children.values():
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    child.kill()
            for handle in handles.values():
                handle.close()
            lock.rollback()
            lock.execute(text("SELECT pg_advisory_unlock(490122883)"))
            lock.commit()


if __name__ == "__main__":
    main()
