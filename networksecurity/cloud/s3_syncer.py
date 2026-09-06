import os
import sys
from pathlib import Path

from networksecurity.exception.exception import NetworkSecurityException
from networksecurity.logging.logger import logging


class S3Sync:
    """Upload/download artifact directories to S3 using boto3.

    The original implementation shelled out to `aws s3 sync` via os.system()
    with an f-string: the path went through a shell, and the exit code was
    never checked, so a failed sync was indistinguishable from a successful
    one. Using boto3 also removes the awscli dependency from the image.
    """

    def __init__(self, region_name: str | None = None):
        self._region = region_name or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("s3", region_name=self._region)
        return self._client

    @staticmethod
    def _split(s3_uri: str):
        if not s3_uri.startswith("s3://"):
            raise ValueError(f"Not an S3 URI: {s3_uri}")
        bucket, _, prefix = s3_uri[5:].partition("/")
        return bucket, prefix.strip("/")

    def sync_folder_to_s3(self, folder: str, aws_bucket_url: str) -> None:
        try:
            bucket, prefix = self._split(aws_bucket_url)
            root = Path(folder)
            if not root.exists():
                logging.warning(f"S3 sync source {folder} does not exist - nothing uploaded.")
                return
            count = 0
            for path in root.rglob("*"):
                if path.is_file():
                    key = f"{prefix}/{path.relative_to(root).as_posix()}" if prefix else path.relative_to(root).as_posix()
                    self.client.upload_file(str(path), bucket, key)
                    count += 1
            logging.info(f"Uploaded {count} file(s) from {folder} to {aws_bucket_url}")
        except Exception as e:
            raise NetworkSecurityException(e, sys)

    def sync_folder_from_s3(self, folder: str, aws_bucket_url: str) -> None:
        try:
            bucket, prefix = self._split(aws_bucket_url)
            paginator = self.client.get_paginator("list_objects_v2")
            count = 0
            for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    rel = obj["Key"][len(prefix):].lstrip("/") if prefix else obj["Key"]
                    dest = Path(folder) / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    self.client.download_file(bucket, obj["Key"], str(dest))
                    count += 1
            logging.info(f"Downloaded {count} file(s) from {aws_bucket_url} to {folder}")
        except Exception as e:
            raise NetworkSecurityException(e, sys)
