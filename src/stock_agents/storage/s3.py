"""S3 / MinIO helper: upload raw API payloads, backtest JSON, and other
artifacts. Uses boto3 with an optional endpoint_url so the same code works
against a local S3-compatible service and AWS S3.

Keys follow the convention:
  raw/<source>/<endpoint>/<YYYY/MM/DD>/<ticker>.json.gz
  backtests/<YYYYMMDD>/<job_id>.json
  reports/<YYYYMMDD>/<report_name>.html
"""

from __future__ import annotations

import gzip
import io
import json
import os
from contextlib import closing
from datetime import date
from typing import Any

try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError
except ImportError:  # pragma: no cover
    boto3 = None  # type: ignore[assignment]
    Config = None  # type: ignore[assignment]


def _client(*, signing: bool = False, probe: bool = False):
    if boto3 is None:
        raise RuntimeError("boto3 not installed; pip install boto3")
    endpoint = os.environ.get("S3_ENDPOINT") or None  # None -> real AWS S3
    if signing:
        endpoint = os.environ.get("S3_PUBLIC_ENDPOINT") or endpoint
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY") or None,
        aws_secret_access_key=os.environ.get("S3_SECRET_KEY") or None,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"} if endpoint else {},
            **({"connect_timeout": 2, "read_timeout": 2, "retries": {"total_max_attempts": 1}}
               if probe else {}),
        ),
    )


def _bucket() -> str:
    b = os.environ.get("S3_BUCKET")
    if not b:
        raise RuntimeError("S3_BUCKET not set")
    return b


def ensure_bucket() -> None:
    """Create the bucket if it doesn't exist (idempotent)."""
    c = _client()
    try:
        c.head_bucket(Bucket=_bucket())
    except ClientError as exc:
        if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 404:
            raise
        c.create_bucket(Bucket=_bucket())


def head_bucket() -> None:
    with closing(_client(probe=True)) as client:
        client.head_bucket(Bucket=_bucket())


def put_raw(source: str, endpoint: str, ticker: str, payload: Any, when: date | None = None) -> str:
    """Store a raw API payload gzipped under raw/..."""
    when = when or date.today()
    key = (
        f"raw/{source}/{endpoint}/{when.year:04d}/{when.month:02d}/{when.day:02d}/{ticker}.json.gz"
    )
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as g:
        g.write(json.dumps(payload, default=str).encode())
    buf.seek(0)
    _client().put_object(
        Bucket=_bucket(),
        Key=key,
        Body=buf.read(),
        ContentType="application/json",
        ContentEncoding="gzip",
    )
    return key


def put_backtest(job_id: str, summary: dict[str, Any], when: date | None = None) -> str:
    when = when or date.today()
    key = f"backtests/{when.strftime('%Y%m%d')}/{job_id}.json"
    _client().put_object(
        Bucket=_bucket(),
        Key=key,
        Body=json.dumps(summary, indent=2, default=str).encode(),
        ContentType="application/json",
        CacheControl="private, no-store",
    )
    return key


def get_object(key: str) -> bytes:
    return _client().get_object(Bucket=_bucket(), Key=key)["Body"].read()


def presigned_url(key: str, expires_in: int = 300) -> str:
    return _client(signing=True).generate_presigned_url(
        "get_object",
        Params={"Bucket": _bucket(), "Key": key, "ResponseCacheControl": "private, no-store"},
        ExpiresIn=expires_in,
    )
