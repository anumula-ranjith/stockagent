"""Run one native Stock Agents service from the repository root."""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps/web"


def object_store(args: argparse.Namespace) -> int:
    settings = {**dotenv_values(ROOT / ".env"), **os.environ}
    endpoint = urlsplit(settings.get("S3_ENDPOINT") or "")
    if endpoint.scheme != "http" or endpoint.hostname not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Set S3_ENDPOINT to the local HTTP address for SeaweedFS.")
    env = os.environ.copy()
    for source, dest in (
        ("S3_ACCESS_KEY", "AWS_ACCESS_KEY_ID"), ("S3_SECRET_KEY", "AWS_SECRET_ACCESS_KEY"),
        ("S3_BUCKET", "S3_BUCKET"),
    ):
        value = settings.get(source)
        if not value:
            raise SystemExit(f"Set {source} in .env before starting the object store.")
        env[dest] = value
    executable = shutil.which(args.executable)
    if not executable:
        raise SystemExit("Install the SeaweedFS weed binary or pass its path with --executable.")
    directory = args.data_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    return subprocess.call([
        executable, "mini", "-ip=127.0.0.1", "-ip.bind=127.0.0.1", "-master.telemetry=false",
        "-master.volumeSizeLimitMB=256", f"-s3.port={endpoint.port or 80}", f"-dir={directory}",
    ], env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    services = parser.add_subparsers(dest="service", required=True)
    for name in ("prepare", "api", "worker", "scheduler", "web", "web-dev"):
        services.add_parser(name)
    store = services.add_parser("object-store", help="start a loopback SeaweedFS S3 endpoint")
    store.add_argument("--data-dir", type=Path, required=True, help="persistent SeaweedFS directory")
    store.add_argument("--executable", default="weed", help="SeaweedFS binary (default: weed on PATH)")
    args = parser.parse_args()
    if args.service == "object-store":
        return object_store(args)
    if args.service in {"web", "web-dev"}:
        node = shutil.which("node")
        next_cli = WEB / "node_modules/next/dist/bin/next"
        if not node or not next_cli.is_file():
            raise SystemExit("Install Node and run pnpm install --frozen-lockfile in apps/web.")
        mode = "start" if args.service == "web" else "dev"
        return subprocess.call([node, str(next_cli), mode, "-H", "127.0.0.1", "-p", "3001"], cwd=WEB)
    if args.service == "prepare":
        from stock_agents.cli import main as cli
        from stock_agents.storage.s3 import ensure_bucket

        cli(["init-db"])
        ensure_bucket()
        print("Artifact bucket ready")
        return 0
    commands = {
        "api": ["uvicorn", "stock_agents.api.main:app", "--host", "127.0.0.1", "--port", "8701"],
        "worker": ["stock_agents.jobs.worker"],
        "scheduler": ["scripts.schedule_daily"],
    }
    return subprocess.call([sys.executable, "-m", *commands[args.service]], cwd=ROOT)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
