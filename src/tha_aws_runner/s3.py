import io
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tqdm import tqdm

from tha_aws_runner.aws_base import AWSBase


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ValueError(f"Invalid S3 URI: {uri!r}. Expected format: s3://bucket/key")
    rest = uri[5:]
    if "/" not in rest:
        raise ValueError(f"Invalid S3 URI: {uri!r}. Missing key after bucket name.")
    bucket, key = rest.split("/", 1)
    if not bucket:
        raise ValueError(f"Invalid S3 URI: {uri!r}. Bucket name is empty.")
    if not key:
        raise ValueError(f"Invalid S3 URI: {uri!r}. Key is empty.")
    return bucket, key


class ThaS3(AWSBase):
    def __init__(
        self,
        *,
        status_cb: Callable[[str], None] | None = None,
        mode: str = "app",
        region: str | None = None,
        profile: str | None = None,
    ) -> None:
        super().__init__(status_cb=status_cb, mode=mode, region=region, profile=profile)
        self._s3: Any = None

    def _client(self, s3: Any = None) -> Any:
        if s3 is not None:
            return s3
        if self._s3 is None:
            self._s3 = self.clients.s3()
        return self._s3

    def upload_file(
        self,
        bucket: str | None = None,
        key: str | None = None,
        *,
        uri: str | None = None,
        local_path: str | None = None,
        data: str | bytes | None = None,
        encoding: str = "utf-8",
        commit: bool = False,
        s3: Any = None,
    ) -> dict:
        if uri is not None:
            bucket, key = _parse_s3_uri(uri)
        if bucket is None or key is None:
            raise ValueError("Provide uri or both bucket and key")

        if local_path is not None and data is not None:
            raise ValueError("Provide local_path or data, not both")
        if local_path is not None:
            body: bytes = Path(local_path).read_bytes()
        elif isinstance(data, str):
            body = data.encode(encoding)
        elif isinstance(data, bytes):
            body = data
        else:
            raise ValueError("Either local_path or data must be provided")

        if not commit:
            result = {"bucket": bucket, "key": key, "status": "dry_run", "bytes": len(body)}
            self.rows = result
            return result

        s3_client = self._client(s3)

        if self.mode == "cli":
            ncols = min(shutil.get_terminal_size(fallback=(85, 24)).columns, 85)
            fileobj = io.BytesIO(body)
            with tqdm(total=len(body), unit="B", unit_scale=True, desc=key, ncols=ncols) as pbar:
                s3_client.upload_fileobj(fileobj, bucket, key, Callback=lambda n: pbar.update(n))
        else:
            s3_client.put_object(Bucket=bucket, Key=key, Body=body)

        result = {"bucket": bucket, "key": key, "status": "uploaded", "bytes": len(body)}
        self.rows = result
        return result

    def list_files(
        self,
        bucket: str,
        prefix: str = "",
        *,
        s3: Any = None,
    ) -> list[str]:
        s3_client = self._client(s3)
        keys: list[str] = []
        paginator = s3_client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        self.rows = keys
        return keys

    def delete_file(
        self,
        bucket: str | None = None,
        key: str | None = None,
        *,
        uri: str | None = None,
        commit: bool = False,
        s3: Any = None,
    ) -> dict:
        if uri is not None:
            bucket, key = _parse_s3_uri(uri)
        if bucket is None or key is None:
            raise ValueError("Provide uri or both bucket and key")

        if not commit:
            result = {"bucket": bucket, "key": key, "status": "dry_run"}
            self.rows = result
            return result

        s3_client = self._client(s3)
        s3_client.delete_object(Bucket=bucket, Key=key)
        result = {"bucket": bucket, "key": key, "status": "deleted"}
        self.rows = result
        return result

    def download_file(
        self,
        bucket: str | None = None,
        key: str | None = None,
        *,
        uri: str | None = None,
        local_path: str | None = None,
        encoding: str | None = None,
        s3: Any = None,
    ) -> dict:
        if uri is not None:
            bucket, key = _parse_s3_uri(uri)
        if bucket is None or key is None:
            raise ValueError("Provide uri or both bucket and key")

        s3_client = self._client(s3)
        response = s3_client.get_object(Bucket=bucket, Key=key)
        content_length: int = response.get("ContentLength", 0)

        if self.mode == "cli":
            ncols = min(shutil.get_terminal_size(fallback=(85, 24)).columns, 85)
            chunks: list[bytes] = []
            with tqdm(
                total=content_length, unit="B", unit_scale=True, desc=key, ncols=ncols
            ) as pbar:
                for chunk in response["Body"].iter_chunks(chunk_size=1024 * 1024):
                    chunks.append(chunk)
                    pbar.update(len(chunk))
            body = b"".join(chunks)
        else:
            body = response["Body"].read()

        result: dict = {"bucket": bucket, "key": key, "status": "downloaded", "bytes": len(body)}

        if local_path is not None:
            Path(local_path).write_bytes(body)
        else:
            result["data"] = body.decode(encoding) if encoding else body

        self.rows = result
        return result
