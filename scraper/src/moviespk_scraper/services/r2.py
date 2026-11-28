"""R2 object storage for posters (plan §10.3 step 5a.4, §7.4.3, P1-23).

S3-compatible client: endpoint `https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com`, region
`auto`, credentials from `R2_ACCESS_KEY_ID`/`R2_SECRET_ACCESS_KEY` (a token scoped to ONE
bucket), bucket from `R2_BUCKET`. Only HEAD and PUT are used.

Write protection (basic by design, OD11): an object over 1 MB is refused, and at most 200
uploads happen per run (thread-safe; the run then alerts `[alert] images: upload-cap`).
Credentials are never logged.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

MAX_OBJECT_BYTES = 1024 * 1024
MAX_UPLOADS_PER_RUN = 200
CONTENT_TYPE = "image/webp"
CACHE_CONTROL = "public, max-age=31536000, immutable"


class R2Error(Exception):
    """An object was refused or R2 failed."""


class UploadCapReached(R2Error):
    """The 200-uploads-per-run cap is used up."""


@dataclass(frozen=True)
class R2Settings:
    account_id: str
    access_key_id: str
    secret_access_key: str
    bucket: str

    @classmethod
    def from_env(cls) -> R2Settings | None:
        values = {
            k: os.environ.get(k, "").strip()
            for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")
        }
        if not all(values.values()):
            return None
        return cls(
            values["R2_ACCOUNT_ID"],
            values["R2_ACCESS_KEY_ID"],
            values["R2_SECRET_ACCESS_KEY"],
            values["R2_BUCKET"],
        )

    def __repr__(self) -> str:  # never show credentials
        return f"R2Settings(bucket={self.bucket!r})"


def make_client(settings: R2Settings) -> Any:
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.account_id}.r2.cloudflarestorage.com",
        region_name="auto",
        aws_access_key_id=settings.access_key_id,
        aws_secret_access_key=settings.secret_access_key,
        config=Config(
            retries={"max_attempts": 3, "mode": "standard"}, connect_timeout=10, read_timeout=30
        ),
    )


class R2Store:
    """HEAD-then-PUT uploads into one bucket, with the per-object and per-run caps."""

    def __init__(self, client: Any, bucket: str, max_uploads: int = MAX_UPLOADS_PER_RUN) -> None:
        self._client = client
        self.bucket = bucket
        self.max_uploads = max_uploads
        self.uploads = 0
        self._lock = threading.Lock()

    @property
    def cap_reached(self) -> bool:
        return self.uploads >= self.max_uploads

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if str(exc.response.get("Error", {}).get("Code")) in ("404", "NoSuchKey", "NotFound"):
                return False
            raise R2Error(f"HEAD failed: {exc.response.get('Error', {}).get('Code')}") from exc
        return True

    def ensure(self, key: str, body: bytes) -> bool:
        """Upload `key` unless it already exists. Returns True when a PUT happened."""
        if len(body) > MAX_OBJECT_BYTES:
            raise R2Error(f"{key}: {len(body)} bytes is over the 1 MB object cap")
        if self.exists(key):
            return False
        with self._lock:
            if self.uploads >= self.max_uploads:
                raise UploadCapReached(f"upload cap of {self.max_uploads} per run reached")
            self.uploads += 1
        try:
            self._client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=body,
                ContentType=CONTENT_TYPE,
                CacheControl=CACHE_CONTROL,
            )
        except ClientError as exc:
            raise R2Error(f"PUT failed: {exc.response.get('Error', {}).get('Code')}") from exc
        return True
