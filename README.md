# tha-aws-runner

[![CI](https://github.com/tha-guy-nate/tha-aws-runner/actions/workflows/ci.yml/badge.svg)](https://github.com/tha-guy-nate/tha-aws-runner/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/tha-guy-nate/tha-aws-runner/graph/badge.svg)](https://codecov.io/gh/tha-guy-nate/tha-aws-runner)
[![PyPI](https://img.shields.io/pypi/v/tha-aws-runner)](https://pypi.org/project/tha-aws-runner/)
[![Python](https://img.shields.io/pypi/pyversions/tha-aws-runner)](https://pypi.org/project/tha-aws-runner/)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)
[![wheel size](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fpypi.org%2Fpypi%2Ftha-aws-runner%2Fjson&label=wheel%20size&query=%24.urls%5B0%5D.size&suffix=%20B)](https://pypi.org/project/tha-aws-runner/#files)

A Tabular Helper API library that wraps common AWS services (DynamoDB, S3, SSM, and DynamoDB GSI queries) with a typed, consistent interface built on boto3.

## Install

```bash
pip install tha-aws-runner
```

## Quick start

```python
from tha_aws_runner import ThaDdb, ThaGsi, ThaS3, ThaSSM

# DynamoDB — fetch a single item by partition key
ddb = ThaDdb(region="us-east-1")
record = ddb.fetch_by_pk("my_table", "pk1", key_name="id", key_type="S")
# {"status": None, "message": None, "pk": "pk1", "table": "my_table", "data": {"name": "Alice"}}

# DynamoDB — batch fetch from CSV rows (uses batch_get_item, chunks at 100, deduplicates)
rows = [{"user_id": "u1", "name": "Alice"}, {"user_id": "u2", "name": "Bob"}]
records = ddb.batch_fetch_by_pk(rows, pk_col="user_id", table_name="users", key_name="user_id", key_type="S")
# {"users": {"u1": {"status": None, "pk": "u1", "table": "users", "data": {"email": "alice@..."}},
#            "u2": {"status": "error", "pk": "u2", "table": "users", "data": None}}}

# DynamoDB — batch fetch with a tqdm progress bar
records = ddb.batch_fetch_by_pk(rows, pk_col="user_id", table_name="users", key_name="user_id", key_type="S", show_progress=True, progress_desc="fetching users")

# DynamoDB — skip rows already flagged "error" or "warning" (default behaviour)
records = ddb.batch_fetch_by_pk(rows, pk_col="user_id", table_name="users", key_name="user_id", key_type="S")
# rows where row["row status"] in ["error", "warning"] are silently dropped before fetching

# DynamoDB — disable row filtering entirely
records = ddb.batch_fetch_by_pk(rows, pk_col="user_id", table_name="users", key_name="user_id", key_type="S", skip_statuses=[])

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

# S3 — batch download from CSV rows, fixed bucket
rows = [{"key": "reports/jan.csv"}, {"key": "reports/feb.csv"}]
results = s3.batch_download(rows, key_col="key", bucket="my-bucket", workers=4)

# S3 — batch download with a tqdm progress bar
results = s3.batch_download(rows, key_col="key", bucket="my-bucket", show_progress=True, progress_desc="downloading")

# S3 — batch download using a full S3 URI column (mixed buckets)
rows = [{"uri": "s3://bucket-a/jan.csv"}, {"uri": "s3://bucket-b/feb.csv"}]
results = s3.batch_download(rows, uri_col="uri")

# S3 — download all files under a prefix to a local directory
results = s3.download_prefix("my-bucket", "reports/2024/", local_dir="/tmp/reports")

# S3 — download prefix with a progress bar
results = s3.download_prefix("my-bucket", "reports/2024/", local_dir="/tmp/reports", show_progress=True, progress_desc="reports/2024/")

# S3 — check whether an object exists
exists = s3.object_exists("my-bucket", "data/file.csv")
exists = s3.object_exists(uri="s3://my-bucket/data/file.csv")

# S3 — copy an object within or between buckets (commit=True required)
result = s3.copy_file("src-bucket", "old/key.csv", "dst-bucket", "new/key.csv", commit=True)
result = s3.copy_file(src_uri="s3://src-bucket/old/key.csv", dst_uri="s3://dst-bucket/new/key.csv", commit=True)

# SSM — read a parameter
ssm = ThaSSM(region="us-east-1")
value = ssm.read_param("/my/app/secret", with_decryption=True)

# GSI — query a Global Secondary Index by partition key value
gsi = ThaGsi(region="us-east-1")
items = gsi.query("orders", "status-index", "PENDING")
# [{"order_id": "o1", "status": "PENDING", ...}, ...]

# GSI — query with a sort key condition
items = gsi.query("orders", "user-created-index", "user_42",
                  sort_key_value="2024-01-01", sort_key_op=">=")

# GSI — query with begins_with
items = gsi.query("events", "type-ts-index", "click",
                  sort_key_value="2024-06", sort_key_op="begins_with")

# GSI — query with between
items = gsi.query("events", "type-ts-index", "click",
                  sort_key_value=("2024-01-01", "2024-06-30"), sort_key_op="between")

# GSI — query with a FilterExpression (applied after key condition, server-side)
items = gsi.query("orders", "status-index", "PENDING",
                  filter_expr="#amt > :min",
                  filter_names={"#amt": "amount"},
                  filter_values={":min": {"N": "100"}})

# GSI — count matching items (uses SELECT COUNT, no item data returned)
n = gsi.count("orders", "status-index", "PENDING")

# GSI — batch query: flat values list
result = gsi.batch_query("orders", "status-index", ["PENDING", "SHIPPED", "DELIVERED"])
# result.results  → {"PENDING": [...], "SHIPPED": [...], "DELIVERED": [...]}
# result.errors   → {} (or {"FAILED_VALUE": <exception>} on partial failure)

# GSI — batch query: CSV-style rows + column name
rows = [{"status": "PENDING", "region": "us"}, {"status": "SHIPPED", "region": "eu"}]
result = gsi.batch_query("orders", "status-index", rows=rows, gsi_col="status")

# GSI — batch query: skip rows already marked "error" or "warning" (default behaviour)
rows = [{"status": "PENDING", "row status": ""}, {"status": "SHIPPED", "row status": "error"}]
result = gsi.batch_query("orders", "status-index", rows=rows, gsi_col="status")
# the "SHIPPED" row is dropped — only "PENDING" is queried

# GSI — batch count: flat values list
result = gsi.batch_count("orders", "status-index", ["PENDING", "SHIPPED", "DELIVERED"])
# result.results  → {"PENDING": 12, "SHIPPED": 5, "DELIVERED": 87}
# result.errors   → {}

# GSI — batch count: CSV-style rows + column name
result = gsi.batch_count("orders", "status-index", rows=rows, gsi_col="status")

# GSI — progress bar (updates as each value completes)
result = gsi.batch_query("orders", "status-index", values, show_progress=True, progress_desc="querying")

# GSI — control thread pool size (default: Python's ThreadPoolExecutor default)
result = gsi.batch_query("orders", "status-index", values, max_workers=8)

# GSI — update all items matching a GSI value (dry run by default, commit=False)
result = gsi.update_by_gsi("orders", "status-index", "PENDING",
                            "status", "S", "PROCESSING")
# [{"order_id": "o1", "status": "dry_run"}, ...]

# GSI — commit the update
result = gsi.update_by_gsi("orders", "status-index", "PENDING",
                            "status", "S", "PROCESSING", commit=True)
# [{"order_id": "o1", "status": "updated", "old": {"status": {"S": "PENDING"}, ...}}, ...]
# No-op (value already matches):  [{"order_id": "o1", "status": "skipped", "old": None, "message": "..."}]
# If the table has a sort key:    [{"order_id": "o1", "created_at": "2024-01-01", "status": "updated", "old": {...}}, ...]
# On per-item failure:            [{"order_id": "o2", "status": "error", "message": "..."}]

# GSI — skip DescribeTable (least-privilege IAM / no control-plane call)
result = gsi.update_by_gsi("orders", "status-index", "PENDING",
                            "status", "S", "PROCESSING",
                            gsi_hash_key="status", gsi_hash_type="S",
                            tbl_pk_name="order_id", tbl_pk_type="S",
                            commit=True)

# GSI — atomic numeric increment with conditional guard (only increments on real value change)
result = gsi.update_by_gsi("orders", "status-index", "PENDING",
                            "status", "N", 1,
                            increment=True, incr_col="retry_count", commit=True)

# Cost tracking — estimate DynamoDB cost for a block of ThaDdb operations
from tha_aws_runner import DdbCostTracker

ddb = ThaDdb(region="us-east-1")
with DdbCostTracker(ddb) as cost:
    ddb.batch_fetch_by_pk(rows, pk_col="id", table_name="users", key_name="id", key_type="S", workers=8)
    ddb.batch_update_by_pk(rows, pk_col="id", key_name="id", key_type="S",
                           update_attr="status", update_type="S", value_col="status",
                           table_name="users", workers=8, commit=True)
print(cost.summary())
# {"usd": 0.004275, "rcu": 12000.0, "wcu": 2100.0, "region": "us-east-1",
#  "tables": {"users": {"rcu": 12000.0, "wcu": 2100.0, "usd": 0.004275}}}

# Cost tracking — ThaGsi operations (pass the gsi instance, not ddb)
gsi = ThaGsi(region="us-east-1")
with DdbCostTracker(gsi) as cost:
    gsi.batch_query("orders", "status-index", ["PENDING", "SHIPPED"])
print(cost.summary())

# Cost tracking — accumulate across multiple blocks (script-run total)
# Each service class has its own session — create one tracker per instance
ddb_tracker = DdbCostTracker(ddb)
gsi_tracker = DdbCostTracker(gsi)
with ddb_tracker:
    ddb.batch_fetch_by_pk(rows, pk_col="id", table_name="students", key_name="id", key_type="S")
with gsi_tracker:
    gsi.batch_query("orders", "status-index", ["PENDING"])
with ddb_tracker:
    ddb.batch_update_by_pk(rows, pk_col="id", key_name="id", key_type="S",
                           update_attr="status", update_type="S", value_col="status",
                           table_name="enrollments", workers=8, commit=True)
print(ddb_tracker.summary())  # totals both ddb blocks
print(gsi_tracker.summary())  # totals gsi block

# GSI — batch update: flat values list (dry run by default)
result = gsi.batch_update_by_gsi(
    "orders", "status-index", ["PENDING", "REVIEW"],
    update_attr="status", update_type="S", update_value="PROCESSING",
)
# result.results → {"PENDING": [{"order_id": "o1", "status": "dry_run"}, ...],
#                   "REVIEW":  [{"order_id": "o2", "status": "dry_run"}, ...]}
# result.errors  → {} (or {"FAILED_VALUE": <exception>} if the GSI query itself failed)

# GSI — batch update: commit + rows input
rows = [{"status": "PENDING", "region": "us"}, {"status": "REVIEW", "region": "eu"}]
result = gsi.batch_update_by_gsi(
    "orders", "status-index",
    rows=rows, gsi_col="status",
    update_attr="status", update_type="S", update_value="PROCESSING",
    commit=True,
)

# GSI — batch update: atomic increment
result = gsi.batch_update_by_gsi(
    "orders", "status-index", ["PENDING", "REVIEW"],
    update_attr="status", update_type="N", update_value=1,
    increment=True, incr_col="retry_count", commit=True,
)
```

## API

### `ThaDdb`

```python
ThaDdb(
    *,
    status_cb=None,
    mode="app",
    region=None,
    profile=None,
    aws_access_key_id=None,
    aws_secret_access_key=None,
    aws_session_token=None,
)
```

| Method | Description |
|--------|-------------|
| `fetch_by_pk(table_name, partition_key, *, fields=None, key_name=None, key_type=None, dynamodb=None)` | Fetch a single item by partition key via `get_item`. Returns `{status, message, pk, table, data}`. `status` is `None` (item found) or `"error"` (item missing or AWS error). Pass `fields={"attr": "DDB_TYPE"}` (e.g. `{"name": "S", "age": "N"}`) to extract specific typed attributes; without it all attributes are returned. `table_name` accepts a full DynamoDB table ARN (`arn:aws:dynamodb:…:table/MyTable`) — the table name is extracted automatically. |
| `batch_fetch_by_pk(rows, pk_col, *, table_name=None, table_name_col=None, key_name=None, key_type=None, fields=None, workers=1, show_progress=False, progress_desc=None, skip_statuses=None, status_col="row status", dynamodb=None)` | Batch-fetch items by partition key via `batch_get_item` (chunks at 100). Each row must have `pk_col`. Provide exactly one of `table_name` (single table) or `table_name_col` (per-row table). Returns `{table: {pk: {status, message, pk, table, data}}}`. `status` is `None` (found) or `"error"` (missing or AWS error). Duplicate PKs are deduplicated before the fetch. Pass `fields={"attr": "DDB_TYPE"}` to extract specific typed attributes; without it all attributes are returned. Chunk-level errors are captured per-chunk; affected PKs get `status: "error"` while remaining chunks still return data. Pass `workers>1` to parallelize chunks across threads. Pass `show_progress=True` to display a tqdm progress bar; use `progress_desc` to set its label. Rows where `status_col` (default `"row status"`) is in `skip_statuses` (default `["error", "warning"]`) are dropped before fetching; pass `skip_statuses=[]` to disable. |
| `update_by_pk(table_name, partition_key, key_name, key_type, update_attr, update_type, update_value, *, increment_attr=None, commit=False, dynamodb=None)` | Update a single attribute with conditional check. Returns `{"pk", "status", ...}` where status is `updated`, `skipped`, `error`, or `dry_run`. |
| `batch_update_by_pk(rows, pk_col, key_name, key_type, update_attr, update_type, value_col, *, table_name=None, table_name_col=None, increment_attr=None, workers=1, show_progress=False, progress_desc=None, commit=False, skip_statuses=None, status_col="row status", dynamodb=None)` | Update an attribute for each row in a list. Provide exactly one of `table_name` (single table) or `table_name_col` (per-row table). Wraps `update_by_pk` per row. Pass `workers>1` for threading. Pass `show_progress=True` to display a tqdm progress bar; use `progress_desc` to set its label. Returns a list of per-row result dicts. Rows where `status_col` (default `"row status"`) is in `skip_statuses` (default `["error", "warning"]`) are dropped before updating; pass `skip_statuses=[]` to disable. |
| `batch_delete_by_pk(rows, pk_col, key_name, key_type, *, table_name=None, table_name_col=None, workers=1, show_progress=False, progress_desc=None, commit=False, skip_statuses=None, status_col="row status", dynamodb=None)` | Delete an item for each row in a list. Provide exactly one of `table_name` (single table) or `table_name_col` (per-row table). Wraps `delete_by_pk` per row. Pass `workers>1` for threading. Pass `show_progress=True` to display a tqdm progress bar; use `progress_desc` to set its label. Returns a list of per-row result dicts. Rows where `status_col` (default `"row status"`) is in `skip_statuses` (default `["error", "warning"]`) are dropped before deleting; pass `skip_statuses=[]` to disable. |
| `batch_write(table_name, items, *, show_progress=False, progress_desc=None, commit=False, dynamodb=None)` | Write up to N items in 25-item chunks with retry. Returns `{"written": N}` or `{"written": N, "status": "dry_run"}`. Does not support `workers` — DDB batch writes serialize deliberately to respect provisioned write throughput and keep retry logic simple. Use `batch_update_by_pk` with `workers` for parallel fan-out writes by partition key. Pass `show_progress=True` to display a tqdm progress bar; use `progress_desc` to set its label. |
| `delete_by_pk(table_name, partition_key, key_name, key_type, *, commit=False, dynamodb=None)` | Delete one item with existence check. Returns `{"pk", "status"}`. |

All write methods default to `commit=False` (dry run) — pass `commit=True` to execute. In dry-run mode the AWS call is skipped and `status` is `"dry_run"`.

All methods that accept `table_name` also accept a full DynamoDB table ARN — the table name is extracted automatically.

> `Scan` is intentionally not implemented — it reads every item in a table and burns read capacity proportional to table size. Use raw boto3 for one-off table scans.

### `ThaGsi`

```python
ThaGsi(
    *,
    status_cb=None,
    mode="app",
    region=None,
    profile=None,
    aws_access_key_id=None,
    aws_secret_access_key=None,
    aws_session_token=None,
)
```

Query DynamoDB Global Secondary Indexes (GSIs). Key schema and attribute types are resolved automatically via `DescribeTable` (cached per instance after first call).

| Method | Description |
|--------|-------------|
| `query(table_name, index_name, value, *, gsi_hash_key=None, gsi_hash_type=None, gsi_range_key=None, gsi_range_type=None, sort_key_value=None, sort_key_op="=", filter_expr=None, filter_names=None, filter_values=None, dynamodb=None)` | Query a GSI for a single partition key value. Returns a `list[dict]` of deserialized items. Paginates automatically. `sort_key_op` must be one of `=`, `<`, `<=`, `>`, `>=`, `begins_with`, `between`. For `between`, pass `sort_key_value` as a 2-tuple: `(low, high)`. `filter_expr` is applied server-side after key conditions; use `filter_names`/`filter_values` for expression attribute substitutions (same format as raw boto3). |
| `count(table_name, index_name, value, *, gsi_hash_key=None, gsi_hash_type=None, gsi_range_key=None, gsi_range_type=None, sort_key_value=None, sort_key_op="=", filter_expr=None, filter_names=None, filter_values=None, dynamodb=None)` | Same as `query` but uses `Select="COUNT"` — no item data is returned, only the matching count. More efficient than `len(query(...))` for large result sets. Returns `int`. |
| `batch_query(table_name, index_name, values=None, *, gsi_hash_key=None, gsi_hash_type=None, gsi_range_key=None, gsi_range_type=None, rows=None, gsi_col=None, sort_key_value=None, sort_key_op="=", filter_expr=None, filter_names=None, filter_values=None, dynamodb=None, max_workers=None, show_progress=False, progress_desc=None, skip_statuses=None, status_col="row status")` | Query multiple partition key values in parallel via `ThreadPoolExecutor`. Provide either a flat `values` list or `rows` + `gsi_col` (a list of dicts and the column name to extract partition key values from) — not both. Returns `BatchQueryResult` with `.results: dict[value, list[dict]]` and `.errors: dict[value, Exception]`. Partial failures are collected — successful values are always returned even if some values error. GSI key schema is resolved once upfront; a bad `index_name` raises immediately before any parallel work starts. Pass `show_progress=True` to display a tqdm progress bar (updates as each value completes); use `progress_desc` to set its label. When `rows` is provided, rows where `status_col` (default `"row status"`) is in `skip_statuses` (default `["error", "warning"]`) are dropped before querying; pass `skip_statuses=[]` to disable. Has no effect when `values` is used. |
| `batch_count(table_name, index_name, values=None, *, gsi_hash_key=None, gsi_hash_type=None, gsi_range_key=None, gsi_range_type=None, rows=None, gsi_col=None, sort_key_value=None, sort_key_op="=", filter_expr=None, filter_names=None, filter_values=None, dynamodb=None, max_workers=None, show_progress=False, progress_desc=None, skip_statuses=None, status_col="row status")` | Same as `batch_query` but counts only. Accepts the same `values` or `rows`+`gsi_col` input. Returns `BatchCountResult` with `.results: dict[value, int]` and `.errors: dict[value, Exception]`. Pass `show_progress=True` to display a tqdm progress bar; use `progress_desc` to set its label. When `rows` is provided, rows where `status_col` (default `"row status"`) is in `skip_statuses` (default `["error", "warning"]`) are dropped before counting; pass `skip_statuses=[]` to disable. Has no effect when `values` is used. |
| `update_by_gsi(table_name, index_name, value, update_attr, update_type, update_value, *, gsi_hash_key=None, gsi_hash_type=None, gsi_range_key=None, gsi_range_type=None, tbl_pk_name=None, tbl_pk_type=None, tbl_sk_name=None, tbl_sk_type=None, increment=False, incr_col=None, sort_key_value=None, sort_key_op="=", filter_expr=None, filter_names=None, filter_values=None, commit=False, dynamodb=None)` | Update a single attribute on every item matching a GSI partition key value. Queries the GSI first to resolve each item's table primary key, then calls `UpdateItem` per item. Returns `list[dict]` — each entry contains the table PK (and SK if present) plus `"status": "dry_run" \| "updated" \| "skipped" \| "error"`. On `"updated"` rows, `"old"` contains the pre-write attribute map. On `"skipped"` rows (value already matched, no write needed), `"old"` is `None`. On per-item error, `"message"` is also included. `commit=False` (default) skips all writes. When `increment=True`, `incr_col` is required; the update uses a conditional `SET` — `incr_col` is incremented only when the value actually changed, preventing double-bumps on retries. Pass `gsi_hash_key`/`gsi_hash_type` together with `tbl_pk_name`/`tbl_pk_type` to fully skip `DescribeTable` — both GSI key schema and table key schema are resolved independently, so both overrides are required. Add `gsi_range_key`/`gsi_range_type` and `tbl_sk_name`/`tbl_sk_type` if the GSI or table also has a sort key. |
| `batch_update_by_gsi(table_name, index_name, values=None, *, gsi_hash_key=None, gsi_hash_type=None, gsi_range_key=None, gsi_range_type=None, tbl_pk_name=None, tbl_pk_type=None, tbl_sk_name=None, tbl_sk_type=None, rows=None, gsi_col=None, update_attr, update_type, update_value, increment=False, incr_col=None, sort_key_value=None, sort_key_op="=", filter_expr=None, filter_names=None, filter_values=None, commit=False, dynamodb=None, max_workers=None, show_progress=False, progress_desc=None, skip_statuses=None, status_col="row status")` | Parallel variant of `update_by_gsi` across multiple GSI values. Accepts the same `values` or `rows`+`gsi_col` input. `update_attr`, `update_type`, and `update_value` are required keyword-only args. Returns `BatchUpdateResult` with `.results: dict[value, list[dict]]` (same per-item shape as `update_by_gsi`, including `"old"` on updated rows and `"skipped"` status for no-op writes) and `.errors: dict[value, Exception]` (values where the GSI query itself failed — no items were updated for those). Per-item `UpdateItem` failures appear inside `results[value]` as `{"status": "error", "message": "..."}` and do not prevent other items in the same value from updating. Pass `show_progress=True` to display a tqdm progress bar; use `progress_desc` to set its label. When `rows` is provided, rows where `status_col` (default `"row status"`) is in `skip_statuses` (default `["error", "warning"]`) are dropped before updating; pass `skip_statuses=[]` to disable. Has no effect when `values` is used. Pass `gsi_hash_key`/`gsi_hash_type` together with `tbl_pk_name`/`tbl_pk_type` to fully skip `DescribeTable` — both overrides are resolved independently and both are required. |

`table_name` accepts a full DynamoDB table ARN — the table name is extracted automatically.

Reserved expression placeholder names (`#_pk`, `#_sk`, `:_pkv`, `:_skv`, `:_skv1`, `:_skv2`) are used internally by `ThaGsi` and will raise `ValueError` if passed in `filter_names`/`filter_values`.

> **Batch scope:** Each batch method (`batch_query`, `batch_count`, `batch_update_by_gsi`) is scoped to a single `table_name` + `index_name`. Multiple tables are not supported within one call — make separate calls per table.

> `Scan` is intentionally not implemented. Use raw boto3 for one-off table scans.

### `ThaS3`

```python
ThaS3(
    *,
    status_cb=None,
    mode="app",
    region=None,
    profile=None,
    aws_access_key_id=None,
    aws_secret_access_key=None,
    aws_session_token=None,
)
```

| Method | Description |
|--------|-------------|
| `upload_file(bucket=None, key=None, *, uri=None, local_path=None, data=None, encoding="utf-8", commit=False, s3=None)` | Upload a local file, raw bytes, or a string to S3. Provide `uri` or both `bucket`+`key`. Provide exactly one of `local_path` or `data`. Strings are encoded using `encoding`. Returns `{"bucket", "key", "status", "bytes"}`. |
| `list_files(bucket, prefix="", *, s3=None)` | List all object keys in a bucket under an optional prefix. Returns a `list[str]` of keys. Paginates automatically. |
| `delete_file(bucket=None, key=None, *, uri=None, commit=False, s3=None)` | Delete an S3 object. Provide `uri` or both `bucket`+`key`. Returns `{"bucket", "key", "status"}`. |
| `download_file(bucket=None, key=None, *, uri=None, local_path=None, encoding=None, s3=None)` | Download an S3 object. Provide `uri` or both `bucket`+`key`. Without `local_path`, returns data in `result["data"]` as `str` (if `encoding` set) or `bytes`. With `local_path`, writes raw bytes to disk. Returns `{"bucket", "key", "status", "bytes"}`. |
| `download_prefix(bucket, prefix="", *, local_dir=None, encoding=None, workers=1, show_progress=False, progress_desc=None, s3=None)` | Download all objects under a prefix (lists then batch-downloads). Equivalent to `aws s3 cp --recursive`. With `local_dir`, files are written to disk preserving the key path structure. Pass `show_progress=True` to display a tqdm progress bar; use `progress_desc` to set its label. Returns a `list[dict]` of per-file results. |
| `batch_download(rows, *, uri_col=None, key_col=None, bucket=None, bucket_col=None, local_dir=None, encoding=None, workers=1, show_progress=False, progress_desc=None, s3=None)` | Download multiple S3 objects from a list of rows. Three modes: (1) `uri_col` — full `s3://` URI per row; (2) `key_col + bucket` — fixed bucket for all rows; (3) `key_col + bucket_col` — per-row bucket. With `local_dir`, files are written to disk preserving the key path structure. Pass `workers>1` to parallelize. Pass `show_progress=True` to display a tqdm progress bar; use `progress_desc` to set its label. Returns a `list[dict]` of per-file results; invalid URIs and download failures are captured per-row as `{"status": "error", "message": msg}` rather than raising. |
| `object_exists(bucket=None, key=None, *, uri=None, s3=None)` | Check whether an S3 object exists via `head_object`. Provide `uri` or both `bucket`+`key`. Returns `True` if the object exists, `False` if it returns 404. Re-raises any other AWS error (e.g. 403 Access Denied). |
| `copy_file(src_bucket=None, src_key=None, dst_bucket=None, dst_key=None, *, src_uri=None, dst_uri=None, commit=False, s3=None)` | Copy an S3 object within or between buckets via `copy_object`. Provide `src_uri`/`dst_uri` or the explicit bucket+key pairs. Returns `{"src_bucket", "src_key", "dst_bucket", "dst_key", "status"}`. |

All `upload_file`, `download_file`, `delete_file`, `object_exists`, and `copy_file` methods accept a full S3 object ARN (`arn:aws:s3:::bucket/key`) in place of `uri`. All methods that accept a `bucket` argument also accept a bucket-only ARN (`arn:aws:s3:::bucket`) — the bucket name is extracted automatically.

### `ThaSSM`

```python
ThaSSM(
    *,
    status_cb=None,
    mode="app",
    region=None,
    profile=None,
    aws_access_key_id=None,
    aws_secret_access_key=None,
    aws_session_token=None,
)
```

| Method | Description |
|--------|-------------|
| `read_param(path, *, with_decryption=False, ssm=None)` | Fetch a single SSM parameter value as a string. `path` accepts a full SSM parameter ARN (`arn:aws:ssm:…:parameter/my/path`) — the path is extracted automatically. |
| `read_params_by_path(path_prefix, *, with_decryption=False, ssm=None)` | Fetch all parameters under a path prefix recursively. Returns `{name: value}`. Paginates automatically. |
| `write_param(path, value, *, param_type="String", overwrite=True, commit=False, ssm=None)` | Write an SSM parameter. Returns `{"path", "status"}`. `path` accepts a full SSM parameter ARN — the path is extracted automatically. |

All methods set `self.rows` to their return value.

`mode="cli"` enables tqdm progress bars. `mode="app"` calls `status_cb(message)` instead.

> **Threading note:** All four service classes (`ThaDdb`, `ThaS3`, `ThaSSM`, `ThaGsi`) are thread-safe — each worker thread gets its own boto3 client via thread-local storage. A single instance can be shared across threads without locking. `ThaGsi.batch_query`, `ThaGsi.batch_count`, and `ThaGsi.batch_update_by_gsi` manage their own `ThreadPoolExecutor` internally. If your caller already parallelizes across multiple `ThaGsi`/`ThaDdb`/`ThaS3` calls, pass `max_workers=1` or `workers=1` (the defaults) to avoid nested pools.

### Helpers

```python
from tha_aws_runner import (
    AWSClients,
    cli_auth_check,
    current_identity,
    parse_arn,
    parse_assumed_role_arn,
)

# Get all boto3 clients from one session (supports inline creds or profile)
clients = AWSClients(region="us-east-1", profile="my-profile")
clients = AWSClients(
    region="us-east-1",
    aws_access_key_id="AKIA...",
    aws_secret_access_key="secret",
    aws_session_token="token",  # optional, for temporary credentials
)
s3 = clients.s3()

# Check the current AWS identity
identity, account_id, role_name, session_name = current_identity(region="us-east-1")

# Guard a script to the expected account/role
if not cli_auth_check(account_id, role_name, "123456789012", "my_role"):
    raise SystemExit("Wrong AWS identity")

# Parse any AWS ARN
result = parse_arn("arn:aws:dynamodb:us-east-1:123456789012:table/MyTable")
# {"partition": "aws", "service": "dynamodb", "region": "us-east-1",
#  "account_id": "123456789012", "resource_type": "table", "resource_id": "MyTable"}

result = parse_arn("arn:aws:sns:us-east-1:123456789012:MyTopic")
# {"partition": "aws", "service": "sns", ..., "resource_type": None, "resource_id": "MyTopic"}
```

All four service classes (`ThaDdb`, `ThaS3`, `ThaSSM`, `ThaGsi`) accept the same `aws_access_key_id`, `aws_secret_access_key`, and `aws_session_token` kwargs for inline credential injection alongside the existing `profile=` option.

`BatchQueryResult`, `BatchCountResult`, and `BatchUpdateResult` are importable directly:

```python
from tha_aws_runner import BatchCountResult, BatchQueryResult, BatchUpdateResult
```

### `DdbCostTracker`

```python
DdbCostTracker(ddb: AWSBase, *, region: str | None = None)
```

Context manager that tallies DynamoDB RCU/WCU consumed during a block of operations and estimates the on-demand USD cost. Accepts any `AWSBase` instance — `ThaDdb`, `ThaGsi`, etc.

Hooks boto3 session events — including per-thread sessions created by `ThreadPoolExecutor` workers — so threaded batch operations are counted correctly. Makes no extra API calls; it reads the `ConsumedCapacity` metadata AWS returns on every operation when `ReturnConsumedCapacity=TOTAL` is requested.

> **Important:** each service class (`ThaDdb`, `ThaGsi`) has its own boto3 session. Pass the instance you are calling operations on. A tracker bound to a `ThaDdb` instance will not capture calls made through a separate `ThaGsi` instance, and vice versa. Create one tracker per instance and accumulate separately if you need a combined total.

`region` defaults to the region of the instance passed in. Used only for pricing lookups; supported regions are `us-east-1`, `us-east-2`, `us-west-1`, `us-west-2`, `ca-central-1`, `eu-west-1`, `eu-west-2`, `eu-west-3`, `eu-central-1`, `eu-north-1`, `ap-southeast-1`, `ap-southeast-2`, `ap-northeast-1`, `ap-northeast-2`, `ap-south-1`, `sa-east-1`. Unknown regions fall back to `us-east-1` pricing.

| Method | Description |
|--------|-------------|
| `summary() -> dict` | Returns `{"usd": float, "rcu": float, "wcu": float, "region": str, "tables": {name: {"rcu": float, "wcu": float, "usd": float}}}`. Thread-safe; safe to call during or after the `with` block. |

Reuse the same `DdbCostTracker` instance across multiple `with` blocks to accumulate a script-run total — the counters are never reset on exit, only on `__init__`.

## Alternatives

- **[boto3](https://boto3.amazonaws.com/v1/documentation/api/latest/index.html)** — the official AWS SDK; `tha-aws-runner` is a thin typed convenience layer on top of it
- **[aioboto3](https://github.com/terrycain/aioboto3)** — async boto3 wrapper for async applications
- **[pynamodb](https://pynamodb.readthedocs.io/)** — ORM-style DynamoDB wrapper with model definitions
- **[aws-lambda-powertools](https://docs.powertools.aws.dev/lambda/python/)** — utilities for Lambda functions including SSM parameter caching

`tha-aws-runner` is intentionally narrow: no ORM, no async, no Lambda-specific features — just a thin typed wrapper for the most common DynamoDB, DynamoDB GSI, S3, and SSM call patterns.

## License

MIT
