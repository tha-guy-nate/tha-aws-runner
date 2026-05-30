import time
from collections.abc import Callable
from typing import Any

from botocore.exceptions import ClientError

from tha_aws_runner.aws_base import AWSBase


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
        partition_keys: list[str],
        *,
        fields: dict[str, str] | None = None,
        key_name: str | None = None,
        key_type: str | None = None,
        dynamodb: Any = None,
    ) -> dict[str, dict]:
        dynamodb = self._client(dynamodb)

        def extract_any(attr: dict) -> Any:
            if not attr:
                return None
            return next(iter(attr.values()), None)

        def extract_typed(attr: dict, expected_type: str = "S") -> Any:
            if not attr:
                return None
            return attr.get(expected_type, None)

        keys = [{key_name: {key_type: pk}} for pk in partition_keys]

        try:
            response = dynamodb.batch_get_item(RequestItems={table_name: {"Keys": keys}})
        except ClientError as e:
            msg = e.response["Error"]["Message"]
            raise RuntimeError(f"DynamoDB batch fetch failed: {msg}") from e

        items = response.get("Responses", {}).get(table_name, [])
        found_ids: set[str] = set()
        records_dict: dict[str, dict] = {}

        for item in items:
            pk_value = extract_typed(item.get(key_name), key_type)  # type: ignore[arg-type]
            if pk_value is None:
                continue
            found_ids.add(pk_value)
            if fields is None:
                records_dict[pk_value] = {
                    k: extract_any(v) for k, v in item.items() if k != key_name
                }
            else:
                records_dict[pk_value] = {
                    field: extract_typed(item.get(field), expected_type)
                    for field, expected_type in fields.items()
                }

        for pk in partition_keys:
            if pk not in found_ids:
                records_dict[pk] = (
                    {"not_found": True}
                    if fields is None
                    else {field: "not found" for field in fields}
                )

        unprocessed = response.get("UnprocessedKeys", {})
        retries = 0
        while unprocessed and retries < 2:
            time.sleep(0.5 * (2**retries))
            try:
                response = dynamodb.batch_get_item(RequestItems=unprocessed)
            except ClientError as e:
                retry_msg = e.response["Error"]["Message"]
                raise RuntimeError(f"DynamoDB batch fetch retry failed: {retry_msg}") from e
            for item in response.get("Responses", {}).get(table_name, []):
                pk_value = extract_typed(item.get(key_name), key_type)  # type: ignore[arg-type]
                if pk_value is None:
                    continue
                found_ids.add(pk_value)
                if fields is None:
                    records_dict[pk_value] = {
                    k: extract_any(v) for k, v in item.items() if k != key_name
                }
                else:
                    records_dict[pk_value] = {
                        field: extract_typed(item.get(field), expected_type)
                        for field, expected_type in fields.items()
                    }
            unprocessed = response.get("UnprocessedKeys", {})
            retries += 1

        if unprocessed:
            raise RuntimeError(f"Unprocessed keys remain after {retries} retries: {unprocessed}")

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
        dynamodb: Any = None,
    ) -> dict:
        dynamodb = self._client(dynamodb)

        MAX_RETRIES = 2
        RETRY_BACKOFF = 0.5

        def to_ddb_attr(val: Any) -> dict:
            if isinstance(val, dict) and len(val) == 1:
                t, v = next(iter(val.items()))
                if t != update_type:
                    raise ValueError(
                        f"Typed value type {t} does not match update_type {update_type}"
                    )
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

        ddb_update_value = to_ddb_attr(update_value)

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
        result: dict

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

                throttled = code in (
                    "ProvisionedThroughputExceededException",
                    "ThrottlingException",
                    "RequestLimitExceeded",
                )
                if throttled:
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

    def batch_put(
        self,
        table_name: str,
        items: list[dict],
        key_name: str,
        *,
        dynamodb: Any = None,
    ) -> dict:
        dynamodb = self._client(dynamodb)

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

            for chunk in self._progress_iter(chunks, total=len(chunks), desc="batch_put"):
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
        dynamodb: Any = None,
    ) -> dict:
        dynamodb = self._client(dynamodb)

        MAX_RETRIES = 2
        RETRY_BACKOFF = 0.5
        key = {key_name: {key_type: partition_key}}
        result: dict

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

                throttled = code in (
                    "ProvisionedThroughputExceededException",
                    "ThrottlingException",
                    "RequestLimitExceeded",
                )
                if throttled:
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
