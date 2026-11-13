"""Mirror screenshots to S3-compatible object storage (AWS S3, Cloudflare R2,
Backblaze B2, MinIO...). Images never touch the git repository.

Configuration comes from environment variables:

  S3_BUCKET            bucket name (required)
  S3_PUBLIC_BASE_URL   public HTTPS base that serves the bucket (required),
                       e.g. https://pub-xxxx.r2.dev or https://cdn.example.com
  S3_ENDPOINT_URL      custom endpoint for non-AWS providers (R2, B2, MinIO)
  S3_PREFIX            key prefix inside the bucket (default: "screens")
  AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_REGION   credentials
"""

from __future__ import annotations

import mimetypes
import os
import re
import urllib.request

USER_AGENT = "600k-ui-patterns-importer/1.0"
EXT_BY_TYPE = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "source"


def fetch(url: str, timeout: int = 60) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        ctype = resp.headers.get_content_type() or "application/octet-stream"
        return resp.read(), ctype


class S3Mirror:
    def __init__(self):
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise SystemExit("Mirroring needs boto3: pip install boto3") from exc

        missing = [v for v in ("S3_BUCKET", "S3_PUBLIC_BASE_URL") if not os.environ.get(v)]
        if missing:
            raise SystemExit(f"Missing environment variables for --mirror: {', '.join(missing)}")
        self.bucket = os.environ["S3_BUCKET"]
        self.public_base = os.environ["S3_PUBLIC_BASE_URL"].rstrip("/")
        if not self.public_base.startswith("https://"):
            raise SystemExit("S3_PUBLIC_BASE_URL must start with https://")
        self.prefix = os.environ.get("S3_PREFIX", "screens").strip("/")
        self.client = boto3.client("s3", endpoint_url=os.environ.get("S3_ENDPOINT_URL") or None)

    def put(self, source_name: str, record_key: str, data: bytes, content_type: str) -> str:
        ext = EXT_BY_TYPE.get(content_type) or mimetypes.guess_extension(content_type) or ".bin"
        key = f"{self.prefix}/{slugify(source_name)}/{slugify(record_key)}{ext}"
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        return f"{self.public_base}/{key}"

    def mirror_url(self, source_name: str, record_key: str, url: str) -> str:
        data, ctype = fetch(url)
        if not ctype.startswith("image/"):
            raise ValueError(f"{url} returned {ctype}, not an image")
        return self.put(source_name, record_key, data, ctype)
