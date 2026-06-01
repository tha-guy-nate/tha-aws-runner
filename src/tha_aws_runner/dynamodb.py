import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from botocore.exceptions import ClientError

from tha_aws_runner.aws_base import AWSBase

_THROTTLE_CODES = frozenset({
    "ProvisionedThroughputExceededException",
    "ThrottlingException",
    "RequestLimitExceeded",
})


def _is_throttled(code: str | None) -> bool:
    return code in _THROTTLE_CODES


def _extract_any(attr: dict) -> Any:
    if not attr:
        return None
    return next(iter(attr.values()), None)


def _extract_typed(attr: dict, expected_type: str = "S") -> Any:
    if not attr:
        return None
    return attr.get(expected_type, None)


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


class ThaDdb(AWSBase):
    def __init__(
        self,
        *,
        status_cb: Callable[[str], None] | None = None,
        mode: str = "app",
        region: str | None = None,
        profile: str | None = None,
    ) -> None:
        super().__init__(status_cb=status_cb, mode=mode, region=region, profile=profile)
        self._dynamodb: Any = None

    def _client(self, dynamodb: Any = None) -> Any:
        if dynamodb is not None:
            return dynamodb
        if self._dynamodb is None:
            self._dynamodb = self.clients.dynamodb()
        return self._dynamodb

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
                "status": "not_found",
                "message": "Item not found",
                "pk": partition_key,
                "table": table_name,
                "data": None,
            }
        elif fields is None:
            result = {
                "status": "ok",
                "message": None,
                "pk": partition_key,
                "table": table_name,
                "data": {k: _extract_any(v) for k, v in item.items() if k != key_name},
            }
        else:
            result = {
                "status": "ok",
                "message": None,
                "pk": partition_key,
                "table": table_name,
                "data": {
                    field: _extract_typed(item.get(field), expected_type)  # type: ignore[arg-type]
                    for field, expected_type in fields.items()
                },
            }
        self.rows = result
        return result

    def batch_fetch_by_pk(
        self,
        table_name: str,
        partition_keys: list[str],
        *,
        fields: dict[str, str] | None = None,
        key_name: str | None = None,
        key_type: str | None = None,
        workers: int = 1,
        dynamodb: Any = None,
    ) -> dict[str, dict[str, dict]]:
        MAX_BATCH_GET = 100
        MAX_RETRIES = 2

        found_ids: set[str] = set()
        records_dict: dict[str, dict] = {}

        def _absorb(items: list[dict]) -> None:
            for item in items:
                pk_value = _extract_typed(item.get(key_name), key_type)  # type: ignore[arg-type]
                if pk_value is None:
                    continue
                found_ids.add(pk_value)
                if fields is None:
                    data = {k: _extract_any(v) for k, v in item.items() if k != key_name}
                else:
                    data = {
                        field: _extract_typed(item.get(field), expected_type)  # type: ignore[arg-type]
                        for field, expected_type in fields.items()
                    }
                records_dict[pk_value] = {
                    "status": "ok",
                    "message": None,
                    "pk": pk_value,
                    "table": table_name,
                    "data": data,
                }

        all_keys = [{key_name: {key_type: pk}} for pk in partition_keys]
        chunks = [all_keys[i : i + MAX_BATCH_GET] for i in range(0, len(all_keys), MAX_BATCH_GET)]

        def _process_chunk(chunk: list[dict], client: Any) -> None:
            chunk_pks = [key[key_name][key_type] for key in chunk]  # type: ignore[index]
            try:
                response = client.batch_get_item(RequestItems={table_name: {"Keys": chunk}})
            except ClientError as e:
                msg = e.response["Error"]["Message"]
                for pk in chunk_pks:
                    found_ids.add(pk)
                    records_dict[pk] = {
                        "status": "error",
                        "message": msg,
                        "pk": pk,
                        "table": table_name,
                        "data": None,
                    }
                return
            _absorb(response.get("Responses", {}).get(table_name, []))
            unprocessed = response.get("UnprocessedKeys", {})
            retries = 0
            while unprocessed and retries < MAX_RETRIES:
                time.sleep(0.5 * (2**retries))
                unprocessed_pks = [
                    key[key_name][key_type]  # type: ignore[index]
                    for key in unprocessed.get(table_name, {}).get("Keys", [])
                ]
                try:
                    response = client.batch_get_item(RequestItems=unprocessed)
                except ClientError as e:
                    retry_msg = e.response["Error"]["Message"]
                    for pk in unprocessed_pks:
                        found_ids.add(pk)
                        records_dict[pk] = {
                            "status": "error",
                            "message": retry_msg,
                            "pk": pk,
                            "table": table_name,
                            "data": None,
                        }
                    return
                _absorb(response.get("Responses", {}).get(table_name, []))
                unprocessed = response.get("UnprocessedKeys", {})
                retries += 1
            if unprocessed:
                remaining_pks = [
                    key[key_name][key_type]  # type: ignore[index]
                    for key in unprocessed.get(table_name, {}).get("Keys", [])
                ]
                for pk in remaining_pks:
                    found_ids.add(pk)
                    records_dict[pk] = {
                        "status": "error",
                        "message": f"Unprocessed after {retries} retries",
                        "pk": pk,
                        "table": table_name,
                        "data": None,
                    }

        if workers > 1:
            def _threaded(chunk: list[dict]) -> None:
                client = dynamodb if dynamodb is not None else self._thread_clients().dynamodb()
                _process_chunk(chunk, client)

            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(_threaded, chunks))
        else:
            client = self._client(dynamodb)
            for chunk in chunks:
                _process_chunk(chunk, client)

        for pk in partition_keys:
            if pk not in found_ids:
                records_dict[pk] = {
                    "status": "not_found",
                    "message": "Item not found",
                    "pk": pk,
                    "table": table_name,
                    "data": None,
                }

        result = {table_name: records_dict}
        self.rows = result
        return result

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
    ) -> dict:
        dynamodb = self._client(dynamodb)

        MAX_RETRIES = 2
        RETRY_BACKOFF = 0.5

        ddb_update_value = _to_ddb_attr(update_value, update_type)

        if not commit:
            result: dict[str, Any] = {"pk": partition_key, "status": "dry_run"}
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
                    self.rows = result
                    return result

                if _is_throttled(code):
                    if attempt == MAX_RETRIES:
                        result = {"pk": partition_key, "status": "error", "message": f"{code}: {msg}"}  # noqa: E501
                        self.rows = result
                        return result
                    time.sleep(RETRY_BACKOFF * (2**attempt))
                    continue

                result = {"pk": partition_key, "status": "error", "message": f"{code}: {msg}"}
                self.rows = result
                return result

        result = {"pk": partition_key, "status": "error", "message": "Max retries exceeded"}
        self.rows = result
        return result

    def batch_update_by_pk(
        self,
        table_name: str,
        rows: list[dict],
        pk_col: str,
        key_name: str,
        key_type: str,
        update_attr: str,
        update_type: str,
        value_col: str,
        *,
        increment_attr: str | None = None,
        workers: int = 1,
        commit: bool = False,
        dynamodb: Any = None,
    ) -> list[dict]:
        results: list[dict] = [{}] * len(rows)

        if workers > 1:
            def _process(args: tuple[int, dict]) -> None:
                idx, row = args
                client = dynamodb if dynamodb is not None else self._thread_clients().dynamodb()
                pk = str(row.get(pk_col) or "")
                val = row.get(value_col)
                results[idx] = self.update_by_pk(
                    table_name, pk, key_name, key_type, update_attr, update_type, val,
                    increment_attr=increment_attr, commit=commit, dynamodb=client,
                )

            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(_process, enumerate(rows)))
        else:
            for idx, row in enumerate(rows):
                pk = str(row.get(pk_col) or "")
                val = row.get(value_col)
                results[idx] = self.update_by_pk(
                    table_name, pk, key_name, key_type, update_attr, update_type, val,
                    increment_attr=increment_attr, commit=commit, dynamodb=dynamodb,
                )

        self.rows = results
        return results

    def batch_delete_by_pk(
        self,
        table_name: str,
        rows: list[dict],
        pk_col: str,
        key_name: str,
        key_type: str,
        *,
        workers: int = 1,
        commit: bool = False,
        dynamodb: Any = None,
    ) -> list[dict]:
        results: list[dict] = [{}] * len(rows)

        if workers > 1:
            def _process(args: tuple[int, dict]) -> None:
                idx, row = args
                client = dynamodb if dynamodb is not None else self._thread_clients().dynamodb()
                pk = str(row.get(pk_col) or "")
                results[idx] = self.delete_by_pk(
                    table_name, pk, key_name, key_type, commit=commit, dynamodb=client,
                )

            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(_process, enumerate(rows)))
        else:
            for idx, row in enumerate(rows):
                pk = str(row.get(pk_col) or "")
                results[idx] = self.delete_by_pk(
                    table_name, pk, key_name, key_type, commit=commit, dynamodb=dynamodb,
                )

        self.rows = results
        return results

    def batch_write(
        self,
        table_name: str,
        items: list[dict],
        *,
        commit: bool = False,
        dynamodb: Any = None,
    ) -> dict:
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

            for chunk in self._progress_iter(chunks, total=len(chunks), desc="batch_write"):
                try:
                    response = dynamodb.batch_write_item(RequestItems={table_name: chunk})
                except ClientError as e:
                    raise RuntimeError(
                        f"DynamoDB batch write failed: {e.response['Error']['Message']}"
                    ) from e

                remaining = response.get("UnprocessedItems", {}).get(table_name, [])
                written += len(chunk) - len(remaining)
                if remaining:
                    unprocessed.setdefault(table_name, []).extend(remaining)

            retries += 1

        if unprocessed:
            raise RuntimeError(
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
    ) -> dict:
        dynamodb = self._client(dynamodb)

        if not commit:
            result: dict[str, Any] = {"pk": partition_key, "status": "dry_run"}
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
                self.rows = result
                return result

            except ClientError as e:
                code = e.response.get("Error", {}).get("Code")
                msg = e.response.get("Error", {}).get("Message")

                if code == "ConditionalCheckFailedException":
                    result = {"pk": partition_key, "status": "skipped", "message": "Item does not exist"}  # noqa: E501
                    self.rows = result
                    return result

                if _is_throttled(code):
                    if attempt == MAX_RETRIES:
                        result = {"pk": partition_key, "status": "error", "message": f"{code}: {msg}"}  # noqa: E501
                        self.rows = result
                        return result
                    time.sleep(RETRY_BACKOFF * (2**attempt))
                    continue

                result = {"pk": partition_key, "status": "error", "message": f"{code}: {msg}"}
                self.rows = result
                return result

        result = {"pk": partition_key, "status": "error", "message": "Max retries exceeded"}
        self.rows = result
        return result
