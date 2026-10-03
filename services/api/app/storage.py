from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, BinaryIO

import boto3
from botocore.client import Config

from app.config import Settings, get_settings


class StorageClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        # Path-style addressing is required for LocalStack. Checksum defaults in
        # recent boto3 reject LocalStack responses, so validate only when required.
        boto_config = Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        )
        self._client = boto3.client(
            "s3",
            endpoint_url=self.settings.s3_endpoint_url,
            aws_access_key_id=self.settings.s3_access_key,
            aws_secret_access_key=self.settings.s3_secret_key,
            region_name=self.settings.s3_region,
            config=boto_config,
        )
        self._public_client = boto3.client(
            "s3",
            endpoint_url=self.settings.s3_public_endpoint_url,
            aws_access_key_id=self.settings.s3_access_key,
            aws_secret_access_key=self.settings.s3_secret_key,
            region_name=self.settings.s3_region,
            config=boto_config,
        )

    def ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self.settings.s3_bucket)
        except Exception:
            self._client.create_bucket(Bucket=self.settings.s3_bucket)
        self._apply_browser_cors()

    def _apply_browser_cors(self) -> None:
        """Allow the dashboard to read objects. Uploads go through the API."""
        try:
            self._client.put_bucket_cors(
                Bucket=self.settings.s3_bucket,
                CORSConfiguration={
                    "CORSRules": [
                        {
                            "AllowedOrigins": ["*"],
                            "AllowedMethods": ["GET", "PUT", "POST", "HEAD"],
                            "AllowedHeaders": ["*"],
                            "ExposeHeaders": ["ETag"],
                            "MaxAgeSeconds": 3600,
                        }
                    ]
                },
            )
        except Exception:
            return

    def build_key(self, project_id: uuid.UUID, kind: str, filename: str) -> str:
        raw = Path(filename).name
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._") or "upload.bin"
        return f"projects/{project_id}/{kind}/{uuid.uuid4().hex}_{safe}"

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.settings.s3_bucket, Key=key)
            return True
        except Exception:
            return False

    def object_size(self, key: str) -> int:
        head = self._client.head_object(Bucket=self.settings.s3_bucket, Key=key)
        return int(head["ContentLength"])

    def upload_fileobj(self, key: str, fileobj: BinaryIO, content_type: str) -> None:
        self._client.upload_fileobj(
            fileobj,
            self.settings.s3_bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )

    def upload_path(self, key: str, path: Path, content_type: str) -> None:
        self._client.upload_file(
            str(path),
            self.settings.s3_bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )

    def download(self, key: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._client.download_file(self.settings.s3_bucket, key, str(dest))

    def copy_object(self, source_key: str, dest_key: str, content_type: str) -> None:
        self._client.copy_object(
            Bucket=self.settings.s3_bucket,
            Key=dest_key,
            CopySource={"Bucket": self.settings.s3_bucket, "Key": source_key},
            ContentType=content_type,
            MetadataDirective="REPLACE",
        )

    def presigned_put(self, key: str, content_type: str, expires: int = 3600) -> str:
        return self._public_client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.settings.s3_bucket,
                "Key": key,
                "ContentType": content_type,
            },
            ExpiresIn=expires,
        )

    def presigned_get(self, key: str, expires: int = 3600) -> str:
        return self._public_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.settings.s3_bucket, "Key": key},
            ExpiresIn=expires,
        )

    def put_bytes(self, key: str, body: bytes, content_type: str = "application/octet-stream") -> None:
        self._client.put_object(
            Bucket=self.settings.s3_bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )

    def put_json(self, key: str, payload: dict[str, Any]) -> None:
        import json

        self.put_bytes(key, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"), "application/json")
