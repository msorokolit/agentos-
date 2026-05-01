"""Tiny S3/MinIO helper for uploading raw document bytes.

We use boto3 if it's installed (production); fall back to a local
filesystem path under ``/tmp/agenticos-uploads`` if not. The fallback
keeps unit tests fast and deterministic.
"""

from __future__ import annotations

import os
from pathlib import Path

from agenticos_shared.logging import get_logger

log = get_logger(__name__)


def _local_dir() -> Path:
    # Fallback path lives under the OS tmpdir; only used when boto3 is
    # missing OR ``AGENTICOS_DISABLE_S3=1`` (used by the test suite).
    import tempfile

    default = Path(tempfile.gettempdir()) / "agenticos-uploads"
    p = Path(os.environ.get("AGENTICOS_LOCAL_UPLOAD_DIR", str(default)))
    p.mkdir(parents=True, exist_ok=True)
    return p


def upload_blob(*, bucket: str, key: str, data: bytes, settings) -> str:
    """Persist ``data`` to s3://bucket/key and return the key.

    Falls back to a local file when boto3 / MinIO are unavailable. We
    short-circuit to the local path when ``AGENTICOS_DISABLE_S3=1`` to
    keep tests fast — boto3's default retry timeouts make hitting a
    nonexistent endpoint take ~30s otherwise.
    """

    if os.environ.get("AGENTICOS_DISABLE_S3") == "1":
        path = _local_dir() / key.replace("/", "__")
        path.write_bytes(data)
        return key

    try:
        import boto3  # type: ignore[import-untyped]
        from botocore.config import Config  # type: ignore[import-untyped]

        client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            config=Config(
                retries={"max_attempts": 1, "mode": "standard"},
                connect_timeout=2,
                read_timeout=5,
            ),
        )
        try:
            client.head_bucket(Bucket=bucket)
        except Exception:
            try:
                client.create_bucket(Bucket=bucket)
            except Exception as exc:
                log.warning("s3_create_bucket_failed", error=str(exc))
        client.put_object(Bucket=bucket, Key=key, Body=data)
        return key
    except Exception as exc:
        log.warning("s3_upload_fallback_local", error=str(exc))
        path = _local_dir() / key.replace("/", "__")
        path.write_bytes(data)
        return key


def download_blob(*, bucket: str, key: str, settings) -> bytes:
    try:
        import boto3  # type: ignore[import-untyped]

        client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
        )
        return client.get_object(Bucket=bucket, Key=key)["Body"].read()
    except Exception as exc:
        log.warning("s3_download_fallback_local", error=str(exc))
        path = _local_dir() / key.replace("/", "__")
        return path.read_bytes()
