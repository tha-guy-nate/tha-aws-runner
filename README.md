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

# DynamoDB — batch fetch by partition key
ddb = ThaDdb(region="us-east-1")
records = ddb.fetch_by_pk("my_table", ["pk1", "pk2"], key_name="id", key_type="S")
# {"pk1": {"name": "Alice"}, "pk2": {"not_found": True}}

# DynamoDB — update a single attribute
result = ddb.update_by_pk("my_table", "pk1", "id", "S", "status", "S", "active")
# {"pk": "pk1", "status": "updated", "old": {...}}

# S3 — upload bytes or a local file (bucket+key or S3 URI)
s3 = ThaS3(region="us-east-1")
s3.upload_file("my-bucket", "data/file.csv", data=b"col1,col2\n1,2")
s3.upload_file("my-bucket", "data/file.csv", local_path="/tmp/file.csv")
s3.upload_file(uri="s3://my-bucket/data/file.csv", data=b"col1,col2\n1,2")

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
| `fetch_by_pk(table_name, partition_keys, *, fields=None, key_name=None, key_type=None, dynamodb=None)` | Batch-fetch items by partition key. Returns `dict[pk → record]`. Missing keys get `{"not_found": True}`. |
| `update_by_pk(table_name, partition_key, key_name, key_type, update_attr, update_type, update_value, *, increment_attr=None, dynamodb=None)` | Update a single attribute with conditional check. Returns `{"pk", "status", ...}` where status is `updated`, `skipped`, or `error`. |
| `batch_put(table_name, items, key_name, *, dynamodb=None)` | Write up to N items in 25-item chunks with retry. Returns `{"written": N}`. |
| `delete_by_pk(table_name, partition_key, key_name, key_type, *, dynamodb=None)` | Delete one item with existence check. Returns `{"pk", "status"}`. |

### `ThaS3`

```python
ThaS3(*, status_cb=None, mode="app", region=None, profile=None)
```

| Method | Description |
|--------|-------------|
| `upload_file(bucket=None, key=None, *, uri=None, local_path=None, data=None, encoding="utf-8", s3=None)` | Upload a local file, raw bytes, or a string to S3. Provide `uri` or both `bucket`+`key`. Provide exactly one of `local_path` or `data`. Strings are encoded using `encoding`. Returns `{"bucket", "key", "status", "bytes"}`. |
| `download_file(bucket=None, key=None, *, uri=None, local_path=None, encoding=None, s3=None)` | Download an S3 object. Provide `uri` or both `bucket`+`key`. Without `local_path`, returns data in `result["data"]` as `str` (if `encoding` set) or `bytes`. With `local_path`, writes raw bytes to disk. Returns `{"bucket", "key", "status", "bytes"}`. |

### `ThaSSM`

```python
ThaSSM(*, status_cb=None, mode="app", region=None, profile=None)
```

| Method | Description |
|--------|-------------|
| `read_param(path, *, with_decryption=False, ssm=None)` | Fetch a single SSM parameter value as a string. |

All methods set `self.rows` to their return value.

`mode="cli"` enables tqdm progress bars. `mode="app"` calls `status_cb(message)` instead.

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
