import io
import shutil
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
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
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        aws_session_token: str | None = None,
    ) -> None:
        super().__init__(
            status_cb=status_cb,
            mode=mode,
            region=region,
            profile=profile,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            aws_session_token=aws_session_token,
        )
        self._s3: Any = None

    def _client(self, s3: Any = None) -> Any:
        if s3 is not None:
            return s3
        with self._client_lock:
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

    def download_prefix(
        self,
        bucket: str,
        prefix: str = "",
        *,
        local_dir: str | None = None,
        encoding: str | None = None,
        workers: int = 1,
        s3: Any = None,
    ) -> list[dict]:
        keys = self.list_files(bucket, prefix, s3=s3)
        rows = [{"key": k} for k in keys]
        return self.batch_download(
            rows, key_col="key", bucket=bucket,
            local_dir=local_dir, encoding=encoding, workers=workers, s3=s3,
        )

    def batch_download(
        self,
        rows: list[dict],
        *,
        uri_col: str | None = None,
        key_col: str | None = None,
        bucket: str | None = None,
        bucket_col: str | None = None,
        local_dir: str | None = None,
        encoding: str | None = None,
        workers: int = 1,
        s3: Any = None,
    ) -> list[dict]:
        if uri_col is not None and key_col is not None:
            raise ValueError("Provide exactly one of uri_col or key_col, not both")
        if uri_col is None and key_col is None:
            raise ValueError("Provide either uri_col or key_col")
        if key_col is not None and (bucket is None) == (bucket_col is None):
            raise ValueError("Provide exactly one of bucket or bucket_col when using key_col")

        def _resolve(row: dict) -> tuple[str, str]:
            if uri_col is not None:
                return _parse_s3_uri(str(row.get(uri_col) or ""))
            b = bucket if bucket is not None else str(row.get(bucket_col) or "")
            k = str(row.get(key_col) or "")
            return b, k

        results: list[dict] = [{}] * len(rows)

        def _one(idx: int, row: dict, client: Any) -> None:
            try:
                b, k = _resolve(row)
            except (ValueError, TypeError) as exc:
                results[idx] = {"status": "error", "message": str(exc)}
                return
            local_path: str | None = None
            if local_dir is not None:
                dest = Path(local_dir) / k
                dest.parent.mkdir(parents=True, exist_ok=True)
                local_path = str(dest)
            try:
                results[idx] = self.download_file(
                    b, k, local_path=local_path, encoding=encoding, s3=client
                )
            except Exception as exc:
                results[idx] = {"bucket": b, "key": k, "status": "error", "message": str(exc)}

        if workers > 1:
            def _threaded(args: tuple[int, dict]) -> None:
                idx, row = args
                client = s3 if s3 is not None else self._thread_clients().s3()
                _one(idx, row, client)

            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(_threaded, enumerate(rows)))
        else:
            single_client = self._client(s3)
            for idx, row in enumerate(rows):
                _one(idx, row, single_client)

        self.rows = results
        return results
