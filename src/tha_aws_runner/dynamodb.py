import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from botocore.exceptions import ClientError

from tha_aws_runner.aws_base import AWSBase
from tha_aws_runner.errors import AwsError
from tha_aws_runner.utils import parse_arn


class ThaDdb(AWSBase):
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
    _THROTTLE_CODES = frozenset({
        "ProvisionedThroughputExceededException",
        "ThrottlingException",
        "RequestLimitExceeded",
    })

    @staticmethod
    def _is_throttled(code: str | None) -> bool:
        return code in ThaDdb._THROTTLE_CODES

    @staticmethod
    def _extract_any(attr: dict) -> Any:
        if not attr:
            return None
        return next(iter(attr.values()), None)

    @staticmethod
    def _extract_typed(attr: dict, expected_type: str = "S") -> Any:
        if not attr:
            return None
        return attr.get(expected_type, None)

    @staticmethod
    def _resolve_table(table_name: str) -> str:
        if not table_name.startswith("arn:"):
            return table_name
        resource_id = parse_arn(table_name).get("resource_id")
        if not resource_id:
            raise ValueError(f"Could not extract table name from ARN: {table_name!r}")
        return resource_id

    @staticmethod
    def _to_ddb_attr(val: Any, update_type: str) -> dict:
        if isinstance(val, dict) and len(val) == 1:
            t, v = next(iter(val.items()))
            if t != update_type:
                raise ValueError(f"Typed value type {t} does not match update_type {update_type}")
            val = v

        t = update_type.upper()

        if t == "BOOL":
            if val is True or val is False:
                return {"BOOL": val}
            if isinstance(val, str):
                s = val.strip().lower()
                if s in ("true", "t", "1", "yes", "y"):
                    return {"BOOL": True}
                if s in ("false", "f", "0", "no", "n"):
                    return {"BOOL": False}
            raise ValueError("BOOL only allows True/False")

        if t == "S":
            if val is None:
                raise ValueError("S does not allow None (use NULL)")
            return {"S": str(val)}

        if t == "N":
            if val is None:
                raise ValueError("N does not allow None (use NULL)")
            if isinstance(val, (int, float)):
                return {"N": str(val)}
            if isinstance(val, str):
                float(val.strip())
                return {"N": val.strip()}
            raise ValueError("N requires int/float or numeric string")

        if t == "NULL":
            if val not in (None, ""):
                raise ValueError("NULL expects None/blank")
            return {"NULL": True}

        raise ValueError(f"Unsupported update_type: {update_type}")

    def _client(self, dynamodb: Any = None) -> Any:
        if dynamodb is not None:
            return dynamodb
        if not hasattr(self._thread_local, "dynamodb"):
            self._thread_local.dynamodb = self._thread_clients().dynamodb()
        return self._thread_local.dynamodb  # type: ignore[no-any-return]

    def fetch_by_pk(
        self,
        table_name: str,
        partition_key: str,
        *,
        fields: dict[str, str] | None = None,
        key_name: str | None = None,
        key_type: str | None = None,
        dynamodb: Any = None,
    ) -> dict:
        table_name = self._resolve_table(table_name)
        dynamodb = self._client(dynamodb)
        key = {key_name: {key_type: partition_key}}
        try:
            response = dynamodb.get_item(TableName=table_name, Key=key)
        except ClientError as e:
            msg = e.response["Error"]["Message"]
            result: dict = {
                "status": "error",
                "message": f"DynamoDB get_item failed: {msg}",
                "pk": partition_key,
                "table": table_name,
                "data": None,
            }
            self.rows = result
            return result
        item = response.get("Item")
        if item is None:
            result = {
                "status": "error",
                "message": "Item not found",
                "pk": partition_key,
                "table": table_name,
                "data": None,
            }
        elif fields is None:
            result = {
                "status": None,
                "message": None,
                "pk": partition_key,
                "table": table_name,
                "data": {k: self._extract_any(v) for k, v in item.items() if k != key_name},
            }
        else:
            result = {
                "status": None,
                "message": None,
                "pk": partition_key,
                "table": table_name,
                "data": {
                    field: self._extract_typed(item.get(field), expected_type)  # type: ignore[arg-type]
                    for field, expected_type in fields.items()
                },
            }
        self.rows = result
        return result

    def batch_fetch_by_pk(
        self,
        rows: list[dict],
        pk_col: str,
        *,
        table_name: str | None = None,
        table_name_col: str | None = None,
        key_name: str | None = None,
        key_type: str | None = None,
        fields: dict[str, str] | None = None,
        workers: int = 1,
        show_progress: bool = False,
        progress_desc: str | None = None,
        dynamodb: Any = None,
    ) -> dict[str, dict[str, dict]]:
        if (table_name is None) == (table_name_col is None):
            raise ValueError("Provide exactly one of table_name or table_name_col")

        if table_name is not None:
            table_name = self._resolve_table(table_name)

        MAX_BATCH_GET = 100
        MAX_RETRIES = 2

        seen: dict[tuple[str, str], None] = {}
        for row in rows:
            _raw = str(row.get(table_name_col) or "")
            tbl = table_name if table_name else self._resolve_table(_raw)
            pk = str(row.get(pk_col) or "")
            if tbl and pk:
                seen[(tbl, pk)] = None
        unique_pairs = list(seen.keys())

        def _make_request(pairs: list[tuple[str, str]]) -> dict[str, Any]:
            req: dict[str, Any] = {}
            for tbl, pk in pairs:
                req.setdefault(tbl, {"Keys": []})["Keys"].append({key_name: {key_type: pk}})
            return req

        records_dict: dict[str, dict[str, dict]] = {}
        found_ids: set[tuple[str, str]] = set()
        chunks = [
            unique_pairs[i : i + MAX_BATCH_GET]
            for i in range(0, len(unique_pairs), MAX_BATCH_GET)
        ]

        def _absorb(
            responses: dict[str, list[dict]],
            local_records: dict[str, dict[str, dict]],
            local_found: set[tuple[str, str]],
        ) -> None:
            for tbl, items in responses.items():
                for item in items:
                    pk_val = self._extract_typed(item.get(key_name), key_type)  # type: ignore[arg-type]
                    if pk_val is None:
                        continue
                    local_found.add((tbl, pk_val))
                    if fields is None:
                        data = {k: self._extract_any(v) for k, v in item.items() if k != key_name}
                    else:
                        data = {
                            f: self._extract_typed(item.get(f), t)  # type: ignore[arg-type]
                            for f, t in fields.items()
                        }
                    local_records.setdefault(tbl, {})[pk_val] = {
                        "status": None,
                        "message": None,
                        "pk": pk_val,
                        "table": tbl,
                        "data": data,
                    }

        def _process_chunk(
            chunk_pairs: list[tuple[str, str]], client: Any
        ) -> tuple[dict[str, dict[str, dict]], set[tuple[str, str]]]:
            local_records: dict[str, dict[str, dict]] = {}
            local_found: set[tuple[str, str]] = set()

            try:
                response = client.batch_get_item(RequestItems=_make_request(chunk_pairs))
            except ClientError as e:
                msg = e.response["Error"]["Message"]
                for tbl, pk in chunk_pairs:
                    local_found.add((tbl, pk))
                    local_records.setdefault(tbl, {})[pk] = {
                        "status": "error", "message": msg,
                        "pk": pk, "table": tbl, "data": None,
                    }
                return local_records, local_found

            _absorb(response.get("Responses", {}), local_records, local_found)
            unprocessed = response.get("UnprocessedKeys", {})
            retries = 0

            while unprocessed and retries < MAX_RETRIES:
                time.sleep(0.5 * (2**retries))
                unprocessed_pairs = [
                    (tbl, key[key_name][key_type])  # type: ignore[index]
                    for tbl, tbl_data in unprocessed.items()
                    for key in tbl_data.get("Keys", [])
                ]
                try:
                    response = client.batch_get_item(RequestItems=unprocessed)
                except ClientError as e:
                    retry_msg = e.response["Error"]["Message"]
                    for tbl, pk in unprocessed_pairs:
                        local_found.add((tbl, pk))
                        local_records.setdefault(tbl, {})[pk] = {
                            "status": "error", "message": retry_msg,
                            "pk": pk, "table": tbl, "data": None,
                        }
                    return local_records, local_found
                _absorb(response.get("Responses", {}), local_records, local_found)
                unprocessed = response.get("UnprocessedKeys", {})
                retries += 1

            if unprocessed:
                for tbl, tbl_data in unprocessed.items():
                    for key in tbl_data.get("Keys", []):
                        pk = key[key_name][key_type]  # type: ignore[index]
                        local_found.add((tbl, pk))
                        local_records.setdefault(tbl, {})[pk] = {
                            "status": "error",
                            "message": f"Unprocessed after {retries} retries",
                            "pk": pk, "table": tbl, "data": None,
                        }

            return local_records, local_found

        def _merge(
            local_records: dict[str, dict[str, dict]], local_found: set[tuple[str, str]]
        ) -> None:
            for tbl, tbl_records in local_records.items():
                records_dict.setdefault(tbl, {}).update(tbl_records)
            found_ids.update(local_found)

        if workers > 1:
            def _threaded(
                chunk_pairs: list[tuple[str, str]],
            ) -> tuple[dict[str, dict[str, dict]], set[tuple[str, str]]]:
                client = dynamodb if dynamodb is not None else self._thread_clients().dynamodb()
                return _process_chunk(chunk_pairs, client)

            with ThreadPoolExecutor(max_workers=workers) as pool:
                for lr, lf in self._progress_iter(
                    pool.map(_threaded, chunks),
                    total=len(chunks), desc=progress_desc, show_progress=show_progress,
                ):
                    _merge(lr, lf)
        else:
            client = self._client(dynamodb)
            for chunk in self._progress_iter(
                chunks, total=len(chunks), desc=progress_desc, show_progress=show_progress,
            ):
                _merge(*_process_chunk(chunk, client))

        for tbl, pk in unique_pairs:
            if (tbl, pk) not in found_ids:
                records_dict.setdefault(tbl, {})[pk] = {
                    "status": "error",
                    "message": "Item not found",
                    "pk": pk, "table": tbl, "data": None,
                }

        self.rows = records_dict
        return records_dict

    def update_by_pk(
        self,
        table_name: str,
        partition_key: str,
        key_name: str,
        key_type: str,
        update_attr: str,
        update_type: str,
        update_value: Any,
        *,
        increment_attr: str | None = None,
        commit: bool = False,
        dynamodb: Any = None,
        _set_rows: bool = True,
    ) -> dict:
        table_name = self._resolve_table(table_name)
        dynamodb = self._client(dynamodb)

        MAX_RETRIES = 2
        RETRY_BACKOFF = 0.5

        ddb_update_value = self._to_ddb_attr(update_value, update_type)

        if not commit:
            result: dict[str, Any] = {"pk": partition_key, "status": "dry_run"}
            if _set_rows:
                self.rows = result
            return result

        expr_attr_names: dict[str, str] = {"#U": update_attr}
        if increment_attr:
            expr_attr_names["#INC"] = increment_attr

        update_expr = "SET #U = :uval"
        if increment_attr:
            update_expr += ", #INC = if_not_exists(#INC, :zero) + :one"

        condition_expr = "attribute_not_exists(#U) OR #U <> :uval"

        eavs: dict[str, Any] = {":uval": ddb_update_value}
        if increment_attr:
            eavs[":zero"] = {"N": "0"}
            eavs[":one"] = {"N": "1"}

        key = {key_name: {key_type: partition_key}}

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = dynamodb.update_item(
                    TableName=table_name,
                    Key=key,
                    UpdateExpression=update_expr,
                    ExpressionAttributeNames=expr_attr_names,
                    ExpressionAttributeValues=eavs,
                    ConditionExpression=condition_expr,
                    ReturnValues="ALL_OLD",
                )
                result = {"pk": partition_key, "status": "updated", "old": resp.get("Attributes")}
                if _set_rows:
                    self.rows = result
                return result

            except ClientError as e:
                code = e.response.get("Error", {}).get("Code")
                msg = e.response.get("Error", {}).get("Message")

                if code == "ConditionalCheckFailedException":
                    result = {
                        "pk": partition_key,
                        "status": "skipped",
                        "message": (
                            f"The source {update_attr} provided is not different"
                            f" from the target {update_attr}."
                        ),
                        "old": None,
                    }
                    if _set_rows:
                        self.rows = result
                    return result

                if self._is_throttled(code):
                    if attempt == MAX_RETRIES:
                        result = {"pk": partition_key, "status": "error", "message": f"{code}: {msg}"}  # noqa: E501
                        if _set_rows:
                            self.rows = result
                        return result
                    time.sleep(RETRY_BACKOFF * (2**attempt))
                    continue

                result = {"pk": partition_key, "status": "error", "message": f"{code}: {msg}"}
                if _set_rows:
                    self.rows = result
                return result

        result = {"pk": partition_key, "status": "error", "message": "Max retries exceeded"}
        if _set_rows:
            self.rows = result
        return result

    def batch_update_by_pk(
        self,
        rows: list[dict],
        pk_col: str,
        key_name: str,
        key_type: str,
        update_attr: str,
        update_type: str,
        value_col: str,
        *,
        table_name: str | None = None,
        table_name_col: str | None = None,
        increment_attr: str | None = None,
        workers: int = 1,
        show_progress: bool = False,
        progress_desc: str | None = None,
        commit: bool = False,
        dynamodb: Any = None,
    ) -> list[dict]:
        if (table_name is None) == (table_name_col is None):
            raise ValueError("Provide exactly one of table_name or table_name_col")

        if table_name is not None:
            table_name = self._resolve_table(table_name)

        results: list[dict] = [{}] * len(rows)

        if workers > 1:
            def _process(args: tuple[int, dict]) -> None:
                idx, row = args
                client = dynamodb if dynamodb is not None else self._thread_clients().dynamodb()
                _raw = str(row.get(table_name_col) or "")
                tbl = table_name if table_name is not None else self._resolve_table(_raw)
                pk = str(row.get(pk_col) or "")
                val = row.get(value_col)
                results[idx] = self.update_by_pk(
                    tbl, pk, key_name, key_type, update_attr, update_type, val,
                    increment_attr=increment_attr, commit=commit, dynamodb=client, _set_rows=False,
                )

            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(self._progress_iter(
                    pool.map(_process, enumerate(rows)),
                    total=len(rows), desc=progress_desc, show_progress=show_progress,
                ))
        else:
            for idx, row in self._progress_iter(
                enumerate(rows), total=len(rows), desc=progress_desc, show_progress=show_progress,
            ):
                _raw = str(row.get(table_name_col) or "")
                tbl = table_name if table_name is not None else self._resolve_table(_raw)
                pk = str(row.get(pk_col) or "")
                val = row.get(value_col)
                results[idx] = self.update_by_pk(
                    tbl, pk, key_name, key_type, update_attr, update_type, val,
                    increment_attr=increment_attr, commit=commit, dynamodb=dynamodb,
                    _set_rows=False,
                )

        self.rows = results
        return results

    def batch_delete_by_pk(
        self,
        rows: list[dict],
        pk_col: str,
        key_name: str,
        key_type: str,
        *,
        table_name: str | None = None,
        table_name_col: str | None = None,
        workers: int = 1,
        show_progress: bool = False,
        progress_desc: str | None = None,
        commit: bool = False,
        dynamodb: Any = None,
    ) -> list[dict]:
        if (table_name is None) == (table_name_col is None):
            raise ValueError("Provide exactly one of table_name or table_name_col")

        if table_name is not None:
            table_name = self._resolve_table(table_name)

        results: list[dict] = [{}] * len(rows)

        if workers > 1:
            def _process(args: tuple[int, dict]) -> None:
                idx, row = args
                client = dynamodb if dynamodb is not None else self._thread_clients().dynamodb()
                _raw = str(row.get(table_name_col) or "")
                tbl = table_name if table_name is not None else self._resolve_table(_raw)
                pk = str(row.get(pk_col) or "")
                results[idx] = self.delete_by_pk(
                    tbl, pk, key_name, key_type, commit=commit, dynamodb=client,
                    _set_rows=False,
                )

            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(self._progress_iter(
                    pool.map(_process, enumerate(rows)),
                    total=len(rows), desc=progress_desc, show_progress=show_progress,
                ))
        else:
            for idx, row in self._progress_iter(
                enumerate(rows), total=len(rows), desc=progress_desc, show_progress=show_progress,
            ):
                _raw = str(row.get(table_name_col) or "")
                tbl = table_name if table_name is not None else self._resolve_table(_raw)
                pk = str(row.get(pk_col) or "")
                results[idx] = self.delete_by_pk(
                    tbl, pk, key_name, key_type, commit=commit, dynamodb=dynamodb,
                    _set_rows=False,
                )

        self.rows = results
        return results

    def batch_write(
        self,
        table_name: str,
        items: list[dict],
        *,
        show_progress: bool = False,
        progress_desc: str | None = None,
        commit: bool = False,
        dynamodb: Any = None,
    ) -> dict:
        table_name = self._resolve_table(table_name)
        dynamodb = self._client(dynamodb)

        if not commit:
            result = {"written": len(items), "status": "dry_run"}
            self.rows = result
            return result

        MAX_RETRIES = 2
        put_requests = [{"PutRequest": {"Item": item}} for item in items]
        unprocessed: dict = {table_name: put_requests}
        retries = 0
        written = 0

        while unprocessed and retries < MAX_RETRIES:
            if retries > 0:
                time.sleep(0.5 * (2**retries))

            batch = list(unprocessed.get(table_name, []))
            chunks = [batch[i : i + 25] for i in range(0, len(batch), 25)]
            unprocessed = {}

            for chunk in self._progress_iter(
                chunks, total=len(chunks), desc=progress_desc, show_progress=show_progress
            ):
                try:
                    response = dynamodb.batch_write_item(RequestItems={table_name: chunk})
                except ClientError as e:
                    raise AwsError(
                        f"DynamoDB batch write failed: {e.response['Error']['Message']}"
                    ) from e

                remaining = response.get("UnprocessedItems", {}).get(table_name, [])
                written += len(chunk) - len(remaining)
                if remaining:
                    unprocessed.setdefault(table_name, []).extend(remaining)

            retries += 1

        if unprocessed:
            raise AwsError(
                f"Unprocessed write requests remain after {retries} retries: {unprocessed}"
            )

        result = {"written": written}
        self.rows = result
        return result

    def delete_by_pk(
        self,
        table_name: str,
        partition_key: str,
        key_name: str,
        key_type: str,
        *,
        commit: bool = False,
        dynamodb: Any = None,
        _set_rows: bool = True,
    ) -> dict:
        table_name = self._resolve_table(table_name)
        dynamodb = self._client(dynamodb)

        if not commit:
            result: dict[str, Any] = {"pk": partition_key, "status": "dry_run"}
            if _set_rows:
                self.rows = result
            return result

        MAX_RETRIES = 2
        RETRY_BACKOFF = 0.5
        key = {key_name: {key_type: partition_key}}

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                dynamodb.delete_item(
                    TableName=table_name,
                    Key=key,
                    ConditionExpression="attribute_exists(#K)",
                    ExpressionAttributeNames={"#K": key_name},
                )
                result = {"pk": partition_key, "status": "deleted"}
                if _set_rows:
                    self.rows = result
                return result

            except ClientError as e:
                code = e.response.get("Error", {}).get("Code")
                msg = e.response.get("Error", {}).get("Message")

                if code == "ConditionalCheckFailedException":
                    result = {"pk": partition_key, "status": "skipped", "message": "Item does not exist"}  # noqa: E501
                    if _set_rows:
                        self.rows = result
                    return result

                if self._is_throttled(code):
                    if attempt == MAX_RETRIES:
                        result = {"pk": partition_key, "status": "error", "message": f"{code}: {msg}"}  # noqa: E501
                        if _set_rows:
                            self.rows = result
                        return result
                    time.sleep(RETRY_BACKOFF * (2**attempt))
                    continue

                result = {"pk": partition_key, "status": "error", "message": f"{code}: {msg}"}
                if _set_rows:
                    self.rows = result
                return result

        result = {"pk": partition_key, "status": "error", "message": "Max retries exceeded"}
        if _set_rows:
            self.rows = result
        return result
