# tha-aws-runner

[![CI](https://github.com/tha-guy-nate/tha-aws-runner/actions/workflows/ci.yml/badge.svg)](https://github.com/tha-guy-nate/tha-aws-runner/actions/workflows/ci.yml)

A Tabular Helper API library that wraps common AWS services (DynamoDB, S3, SSM) with a typed, consistent interface built on boto3.

## Install

```bash
pip install tha-aws-runner
```

## Quick start

```python
from tha_aws_runner import ThaDdb, ThaS3, ThaSSM

# DynamoDB — fetch a single item by partition key
ddb = ThaDdb(region="us-east-1")
record = ddb.fetch_by_pk("my_table", "pk1", key_name="id", key_type="S")
# {"status": None, "message": None, "pk": "pk1", "table": "my_table", "data": {"name": "Alice"}}

# DynamoDB — batch fetch by partition key (uses batch_get_item, chunks at 100)
rows = [{"id": "pk1"}, {"id": "pk2"}]
records = ddb.batch_fetch_by_pk(rows, pk_col="id", table_name="my_table", key_name="id", key_type="S")
# {"my_table": {"pk1": {"status": None, "pk": "pk1", "table": "my_table", "data": {"name": "Alice"}},
#               "pk2": {"status": "error", "pk": "pk2", "table": "my_table", "data": None}}}

# DynamoDB — multi-table batch fetch (table name comes from each row)
rows = [{"id": "pk1", "tbl": "orders"}, {"id": "pk2", "tbl": "users"}]
records = ddb.batch_fetch_by_pk(rows, pk_col="id", table_name_col="tbl", key_name="id", key_type="S")

# DynamoDB — update a single attribute (commit=True required to execute)
result = ddb.update_by_pk("my_table", "pk1", "id", "S", "status", "S", "active", commit=True)
# {"pk": "pk1", "status": "updated", "old": {...}}

# S3 — upload bytes or a local file (bucket+key or S3 URI)
s3 = ThaS3(region="us-east-1")
s3.upload_file("my-bucket", "data/file.csv", data=b"col1,col2\n1,2", commit=True)
s3.upload_file("my-bucket", "data/file.csv", local_path="/tmp/file.csv", commit=True)
s3.upload_file(uri="s3://my-bucket/data/file.csv", data=b"col1,col2\n1,2", commit=True)

# S3 — download to memory or a local file (bucket+key or S3 URI)
result = s3.download_file("my-bucket", "data/file.csv")
# {"bucket": "my-bucket", "key": "data/file.csv", "status": "downloaded", "bytes": 13, "data": b"..."}
s3.download_file("my-bucket", "data/file.csv", local_path="/tmp/out.csv")
s3.download_file(uri="s3://my-bucket/data/file.csv", local_path="/tmp/out.csv")

# SSM — read a parameter
ssm = ThaSSM(region="us-east-1")
value = ssm.read_param("/my/app/secret", with_decryption=True)
```

## API

### `ThaDdb`

```python
ThaDdb(*, status_cb=None, mode="app", region=None, profile=None)
```

| Method | Description |
|--------|-------------|
| `fetch_by_pk(table_name, partition_key, *, fields=None, key_name=None, key_type=None, dynamodb=None)` | Fetch a single item by partition key via `get_item`. Returns `{status, message, pk, table, data}`. `status` is `None` (item found) or `"error"` (item missing or AWS error). |
| `batch_fetch_by_pk(rows, pk_col, *, table_name=None, table_name_col=None, key_name=None, key_type=None, fields=None, workers=1, dynamodb=None)` | Batch-fetch items by partition key via `batch_get_item` (chunks at 100). Each row must have `pk_col`. Provide exactly one of `table_name` (single table) or `table_name_col` (per-row table). Returns `{table: {pk: {status, message, pk, table, data}}}`. `status` is `None` (found) or `"error"` (missing or AWS error). Duplicate PKs are deduplicated before the fetch. Chunk-level errors are captured per-chunk; affected PKs get `status: "error"` while remaining chunks still return data. Pass `workers>1` to parallelize chunks across threads. |
| `update_by_pk(table_name, partition_key, key_name, key_type, update_attr, update_type, update_value, *, increment_attr=None, commit=False, dynamodb=None)` | Update a single attribute with conditional check. Returns `{"pk", "status", ...}` where status is `updated`, `skipped`, `error`, or `dry_run`. |
| `batch_update_by_pk(table_name, rows, pk_col, key_name, key_type, update_attr, update_type, value_col, *, increment_attr=None, workers=1, commit=False, dynamodb=None)` | Update an attribute for each row in a list. Wraps `update_by_pk` per row. Pass `workers>1` for threading. Returns a list of per-row result dicts. |
| `batch_delete_by_pk(table_name, rows, pk_col, key_name, key_type, *, workers=1, commit=False, dynamodb=None)` | Delete an item for each row in a list. Wraps `delete_by_pk` per row. Pass `workers>1` for threading. Returns a list of per-row result dicts. |
| `batch_write(table_name, items, *, commit=False, dynamodb=None)` | Write up to N items in 25-item chunks with retry. Returns `{"written": N}` or `{"written": N, "status": "dry_run"}`. Does not support `workers` — DDB batch writes serialize deliberately to respect provisioned write throughput and keep retry logic simple. Use `batch_update_by_pk` with `workers` for parallel fan-out writes by partition key. |
| `delete_by_pk(table_name, partition_key, key_name, key_type, *, commit=False, dynamodb=None)` | Delete one item with existence check. Returns `{"pk", "status"}`. |

All write methods default to `commit=False` (dry run) — pass `commit=True` to execute. In dry-run mode the AWS call is skipped and `status` is `"dry_run"`.

> GSI (Global Secondary Index) support for `ThaDdb` is planned for a future version.

### `ThaS3`

```python
ThaS3(*, status_cb=None, mode="app", region=None, profile=None)
```

| Method | Description |
|--------|-------------|
| `upload_file(bucket=None, key=None, *, uri=None, local_path=None, data=None, encoding="utf-8", commit=False, s3=None)` | Upload a local file, raw bytes, or a string to S3. Provide `uri` or both `bucket`+`key`. Provide exactly one of `local_path` or `data`. Strings are encoded using `encoding`. Returns `{"bucket", "key", "status", "bytes"}`. |
| `list_files(bucket, prefix="", *, s3=None)` | List all object keys in a bucket under an optional prefix. Returns a `list[str]` of keys. Paginates automatically. |
| `delete_file(bucket=None, key=None, *, uri=None, commit=False, s3=None)` | Delete an S3 object. Provide `uri` or both `bucket`+`key`. Returns `{"bucket", "key", "status"}`. |
| `download_file(bucket=None, key=None, *, uri=None, local_path=None, encoding=None, s3=None)` | Download an S3 object. Provide `uri` or both `bucket`+`key`. Without `local_path`, returns data in `result["data"]` as `str` (if `encoding` set) or `bytes`. With `local_path`, writes raw bytes to disk. Returns `{"bucket", "key", "status", "bytes"}`. |
| `download_prefix(bucket, prefix="", *, local_dir=None, encoding=None, workers=1, s3=None)` | Download all objects under a prefix (lists then batch-downloads). Equivalent to `aws s3 cp --recursive`. With `local_dir`, files are written to disk preserving the key path structure. Returns a `list[dict]` of per-file results. |
| `batch_download(rows, *, uri_col=None, key_col=None, bucket=None, bucket_col=None, local_dir=None, encoding=None, workers=1, s3=None)` | Download multiple S3 objects from a list of rows. Three modes: (1) `uri_col` — full `s3://` URI per row; (2) `key_col + bucket` — fixed bucket for all rows; (3) `key_col + bucket_col` — per-row bucket. With `local_dir`, files are written to disk preserving the key path structure. Pass `workers>1` to parallelize. Returns a `list[dict]` of per-file results; invalid URIs and download failures are captured per-row as `{"status": "error", "message": msg}` rather than raising. |

### `ThaSSM`

```python
ThaSSM(*, status_cb=None, mode="app", region=None, profile=None)
```

| Method | Description |
|--------|-------------|
| `read_param(path, *, with_decryption=False, ssm=None)` | Fetch a single SSM parameter value as a string. |
| `read_params_by_path(path_prefix, *, with_decryption=False, ssm=None)` | Fetch all parameters under a path prefix recursively. Returns `{name: value}`. Paginates automatically. |
| `write_param(path, value, *, param_type="String", overwrite=True, commit=False, ssm=None)` | Write an SSM parameter. Returns `{"path", "status"}`. |

All methods set `self.rows` to their return value.

`mode="cli"` enables tqdm progress bars. `mode="app"` calls `status_cb(message)` instead.

> **Threading note:** If your runner already parallelizes calls into `ThaDdb` / `ThaS3` (e.g. via your own `ThreadPoolExecutor`), pass `workers=1` (the default) to avoid nested thread pools. Use the library's `workers>1` when you have a single batch to process and want the library to manage the parallelism.

### Helpers

```python
from tha_aws_runner import AWSClients, current_identity, parse_assumed_role_arn, cli_auth_check

# Get all boto3 clients from one session
clients = AWSClients(region="us-east-1", profile="my-profile")
s3 = clients.s3()

# Check the current AWS identity
identity, account_id, role_name, session_name = current_identity(region="us-east-1")

# Guard a script to the expected account/role
if not cli_auth_check(account_id, role_name, "123456789012", "my_role"):
    raise SystemExit("Wrong AWS identity")
```

## Alternatives

- **[boto3](https://boto3.amazonaws.com/v1/documentation/api/latest/index.html)** — the official AWS SDK; `tha-aws-runner` is a thin typed convenience layer on top of it
- **[aioboto3](https://github.com/terrycain/aioboto3)** — async boto3 wrapper for async applications
- **[pynamodb](https://pynamodb.readthedocs.io/)** — ORM-style DynamoDB wrapper with model definitions
- **[aws-lambda-powertools](https://docs.powertools.aws.dev/lambda/python/)** — utilities for Lambda functions including SSM parameter caching

`tha-aws-runner` is intentionally narrow: no ORM, no async, no Lambda-specific features — just a thin typed wrapper for the most common DynamoDB, S3, and SSM call patterns.

## License

MIT
