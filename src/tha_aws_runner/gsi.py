from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from tha_aws_runner.aws_base import AWSBase
from tha_aws_runner.utils import parse_arn

_VALID_SK_OPS = frozenset({"=", "<", "<=", ">", ">=", "begins_with", "between"})
_RESERVED = frozenset({"#_pk", "#_sk", ":_pkv", ":_skv", ":_skv1", ":_skv2"})


def _deser_attr(attr: dict[str, Any]) -> Any:
    if not attr:
        return None
    return next(iter(attr.values()), None)


def _ddb_val(type_key: str, v: Any) -> dict[str, Any]:
    return {"B": v} if type_key == "B" else {type_key: str(v)}


@dataclass
class BatchQueryResult:
    results: dict[Any, list[dict[str, Any]]] = field(default_factory=dict)
    errors: dict[Any, Exception] = field(default_factory=dict)


@dataclass
class BatchCountResult:
    results: dict[Any, int] = field(default_factory=dict)
    errors: dict[Any, Exception] = field(default_factory=dict)


@dataclass
class BatchUpdateResult:
    results: dict[Any, list[dict[str, Any]]] = field(default_factory=dict)
    errors: dict[Any, Exception] = field(default_factory=dict)


class ThaGsi(AWSBase):
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
        self._table_cache: dict[str, Any] = {}
        self._table_cache_lock = Lock()

    @staticmethod
    def _resolve_table(table_name: str) -> str:
        if not table_name.startswith("arn:"):
            return table_name
        resource_id = parse_arn(table_name).get("resource_id")
        if not resource_id:
            raise ValueError(f"Could not extract table name from ARN: {table_name!r}")
        return resource_id

    def _client(self, dynamodb: Any = None) -> Any:
        if dynamodb is not None:
            return dynamodb
        if not hasattr(self._thread_local, "dynamodb"):
            self._thread_local.dynamodb = self._thread_clients().dynamodb()
        return self._thread_local.dynamodb  # type: ignore[no-any-return]

    def _get_table_desc(self, table_name: str, client: Any) -> dict[str, Any]:
        if table_name in self._table_cache:
            return self._table_cache[table_name]  # type: ignore[no-any-return]
        with self._table_cache_lock:
            if table_name not in self._table_cache:
                resp = client.describe_table(TableName=table_name)
                self._table_cache[table_name] = resp["Table"]
        return self._table_cache[table_name]  # type: ignore[no-any-return]

    def _resolve_gsi_keys(
        self, table_name: str, index_name: str, client: Any
    ) -> tuple[str, str, str | None, str | None]:
        table_desc = self._get_table_desc(table_name, client)

        gsi_list = table_desc.get("GlobalSecondaryIndexes", [])
        gsi = next((g for g in gsi_list if g["IndexName"] == index_name), None)
        if gsi is None:
            raise ValueError(f"GSI {index_name!r} not found on table {table_name!r}")

        pk_name: str | None = next(
            (k["AttributeName"] for k in gsi["KeySchema"] if k["KeyType"] == "HASH"), None
        )
        if pk_name is None:
            raise ValueError(f"No HASH key found in GSI {index_name!r}")

        sk_name: str | None = next(
            (k["AttributeName"] for k in gsi["KeySchema"] if k["KeyType"] == "RANGE"), None
        )

        attr_defs = table_desc.get("AttributeDefinitions", [])

        pk_type: str | None = next(
            (a["AttributeType"] for a in attr_defs if a["AttributeName"] == pk_name), None
        )
        if pk_type is None:
            raise ValueError(f"AttributeDefinition not found for {pk_name!r}")

        sk_type: str | None = None
        if sk_name is not None:
            sk_type = next(
                (a["AttributeType"] for a in attr_defs if a["AttributeName"] == sk_name), None
            )
            if sk_type is None:
                raise ValueError(f"AttributeDefinition not found for {sk_name!r}")

        return pk_name, pk_type, sk_name, sk_type

    def _resolve_table_keys(
        self, table_name: str, client: Any
    ) -> tuple[str, str, str | None, str | None]:
        table_desc = self._get_table_desc(table_name, client)
        key_schema = table_desc.get("KeySchema", [])

        pk_name: str | None = next(
            (k["AttributeName"] for k in key_schema if k["KeyType"] == "HASH"), None
        )
        if pk_name is None:
            raise ValueError(f"No HASH key found in table {table_name!r}")

        sk_name: str | None = next(
            (k["AttributeName"] for k in key_schema if k["KeyType"] == "RANGE"), None
        )

        attr_defs = table_desc.get("AttributeDefinitions", [])
        pk_type: str | None = next(
            (a["AttributeType"] for a in attr_defs if a["AttributeName"] == pk_name), None
        )
        if pk_type is None:
            raise ValueError(f"AttributeDefinition not found for table PK {pk_name!r}")

        sk_type: str | None = None
        if sk_name is not None:
            sk_type = next(
                (a["AttributeType"] for a in attr_defs if a["AttributeName"] == sk_name), None
            )
            if sk_type is None:
                raise ValueError(f"AttributeDefinition not found for table SK {sk_name!r}")

        return pk_name, pk_type, sk_name, sk_type

    def _build_query_kwargs(
        self,
        table_name: str,
        index_name: str,
        value: Any,
        pk_name: str,
        pk_type: str,
        sk_name: str | None,
        sk_type: str | None,
        *,
        sort_key_value: Any,
        sort_key_op: str,
        filter_expr: str | None,
        filter_names: dict[str, str] | None,
        filter_values: dict[str, dict] | None,
    ) -> dict[str, Any]:
        if sort_key_value is not None:
            if sk_name is None or sk_type is None:
                raise ValueError(f"GSI {index_name!r} has no sort key")
            if sort_key_op not in _VALID_SK_OPS:
                raise ValueError(
                    f"Invalid sort_key_op {sort_key_op!r}. Valid: {sorted(_VALID_SK_OPS)}"
                )
            if sort_key_op == "between" and not (
                isinstance(sort_key_value, (list, tuple)) and len(sort_key_value) == 2
            ):
                raise ValueError(
                    "sort_key_op='between' requires sort_key_value as a 2-element tuple"
                )

        if filter_values is not None and filter_expr is None:
            raise ValueError("filter_values requires filter_expr")

        conflicts: set[str] = set()
        if filter_names:
            conflicts |= set(filter_names) & _RESERVED
        if filter_values:
            conflicts |= set(filter_values) & _RESERVED
        if conflicts:
            raise ValueError(
                f"filter_names/filter_values use reserved placeholders: {conflicts}"
            )

        expr_names: dict[str, str] = {"#_pk": pk_name}
        expr_vals: dict[str, Any] = {":_pkv": _ddb_val(pk_type, value)}
        kce = "#_pk = :_pkv"

        if sort_key_value is not None:
            expr_names["#_sk"] = sk_name  # type: ignore[assignment]
            if sort_key_op == "between":
                v1, v2 = sort_key_value
                expr_vals[":_skv1"] = _ddb_val(sk_type, v1)  # type: ignore[arg-type]
                expr_vals[":_skv2"] = _ddb_val(sk_type, v2)  # type: ignore[arg-type]
                kce += " AND #_sk BETWEEN :_skv1 AND :_skv2"
            elif sort_key_op == "begins_with":
                expr_vals[":_skv"] = _ddb_val(sk_type, sort_key_value)  # type: ignore[arg-type]
                kce += " AND begins_with(#_sk, :_skv)"
            else:
                expr_vals[":_skv"] = _ddb_val(sk_type, sort_key_value)  # type: ignore[arg-type]
                kce += f" AND #_sk {sort_key_op} :_skv"

        if filter_names:
            expr_names.update(filter_names)
        if filter_values:
            expr_vals.update(filter_values)

        kwargs: dict[str, Any] = {
            "TableName": table_name,
            "IndexName": index_name,
            "KeyConditionExpression": kce,
            "ExpressionAttributeNames": expr_names,
            "ExpressionAttributeValues": expr_vals,
        }
        if filter_expr is not None:
            kwargs["FilterExpression"] = filter_expr

        return kwargs

    def _run_query(self, kwargs: dict[str, Any], client: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        kw = dict(kwargs)
        while True:
            resp = client.query(**kw)
            for item in resp.get("Items", []):
                items.append({k: _deser_attr(v) for k, v in item.items()})
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kw["ExclusiveStartKey"] = last
        return items

    def _run_count(self, kwargs: dict[str, Any], client: Any) -> int:
        kw = dict(kwargs)
        kw["Select"] = "COUNT"
        total = 0
        while True:
            resp = client.query(**kw)
            total += resp.get("Count", 0)
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kw["ExclusiveStartKey"] = last
        return total

    def query(
        self,
        table_name: str,
        index_name: str,
        value: Any,
        *,
        sort_key_value: Any = None,
        sort_key_op: str = "=",
        filter_expr: str | None = None,
        filter_names: dict[str, str] | None = None,
        filter_values: dict[str, dict] | None = None,
        dynamodb: Any = None,
    ) -> list[dict[str, Any]]:
        table_name = self._resolve_table(table_name)
        client = self._client(dynamodb)
        pk_name, pk_type, sk_name, sk_type = self._resolve_gsi_keys(
            table_name, index_name, client
        )
        kwargs = self._build_query_kwargs(
            table_name, index_name, value, pk_name, pk_type, sk_name, sk_type,
            sort_key_value=sort_key_value, sort_key_op=sort_key_op,
            filter_expr=filter_expr, filter_names=filter_names, filter_values=filter_values,
        )
        items = self._run_query(kwargs, client)
        self.rows = items
        return items

    def count(
        self,
        table_name: str,
        index_name: str,
        value: Any,
        *,
        sort_key_value: Any = None,
        sort_key_op: str = "=",
        filter_expr: str | None = None,
        filter_names: dict[str, str] | None = None,
        filter_values: dict[str, dict] | None = None,
        dynamodb: Any = None,
    ) -> int:
        table_name = self._resolve_table(table_name)
        client = self._client(dynamodb)
        pk_name, pk_type, sk_name, sk_type = self._resolve_gsi_keys(
            table_name, index_name, client
        )
        kwargs = self._build_query_kwargs(
            table_name, index_name, value, pk_name, pk_type, sk_name, sk_type,
            sort_key_value=sort_key_value, sort_key_op=sort_key_op,
            filter_expr=filter_expr, filter_names=filter_names, filter_values=filter_values,
        )
        total = self._run_count(kwargs, client)
        self.rows = total
        return total

    def update_by_gsi(
        self,
        table_name: str,
        index_name: str,
        value: Any,
        update_attr: str,
        update_type: str,
        update_value: Any,
        *,
        increment: bool = False,
        incr_col: str | None = None,
        sort_key_value: Any = None,
        sort_key_op: str = "=",
        filter_expr: str | None = None,
        filter_names: dict[str, str] | None = None,
        filter_values: dict[str, dict] | None = None,
        commit: bool = False,
        dynamodb: Any = None,
    ) -> list[dict[str, Any]]:
        if increment and incr_col is None:
            raise ValueError("incr_col is required when increment=True")
        if incr_col is not None and not increment:
            raise ValueError("incr_col requires increment=True")
        table_name = self._resolve_table(table_name)
        client = self._client(dynamodb)
        gsi_pk_name, gsi_pk_type, gsi_sk_name, gsi_sk_type = self._resolve_gsi_keys(
            table_name, index_name, client
        )
        tbl_pk_name, tbl_pk_type, tbl_sk_name, tbl_sk_type = self._resolve_table_keys(
            table_name, client
        )

        gsi_kwargs = self._build_query_kwargs(
            table_name, index_name, value,
            gsi_pk_name, gsi_pk_type, gsi_sk_name, gsi_sk_type,
            sort_key_value=sort_key_value, sort_key_op=sort_key_op,
            filter_expr=filter_expr, filter_names=filter_names, filter_values=filter_values,
        )
        items = self._run_query(gsi_kwargs, client)

        results: list[dict[str, Any]] = []

        for item in items:
            tbl_pk_val = item.get(tbl_pk_name)
            row: dict[str, Any] = {tbl_pk_name: tbl_pk_val}

            if tbl_sk_name is not None:
                row[tbl_sk_name] = item.get(tbl_sk_name)

            if not commit:
                row["status"] = "dry_run"
                results.append(row)
                continue

            try:
                key: dict[str, Any] = {tbl_pk_name: _ddb_val(tbl_pk_type, tbl_pk_val)}
                if tbl_sk_name is not None and tbl_sk_type is not None:
                    key[tbl_sk_name] = _ddb_val(tbl_sk_type, item.get(tbl_sk_name))
                upd_expr = "ADD #_upd :_updv" if increment else "SET #_upd = :_updv"
                upd_attr = incr_col if increment else update_attr
                client.update_item(
                    TableName=table_name,
                    Key=key,
                    UpdateExpression=upd_expr,
                    ExpressionAttributeNames={"#_upd": upd_attr},
                    ExpressionAttributeValues={":_updv": _ddb_val(update_type, update_value)},
                )
                row["status"] = "updated"
            except Exception as e:
                row["status"] = "error"
                row["message"] = str(e)

            results.append(row)

        self.rows = results
        return results

    @staticmethod
    def _resolve_batch_values(
        values: list[Any] | None,
        rows: list[dict[str, Any]] | None,
        gsi_col: str | None,
        skip_statuses: list[str],
        status_col: str,
    ) -> list[Any]:
        if values is not None and rows is not None:
            raise ValueError("Provide either values or rows, not both")
        if rows is not None:
            if gsi_col is None:
                raise ValueError("gsi_col is required when rows is provided")
            filtered = [r for r in rows if r.get(status_col) not in skip_statuses]
            return [row[gsi_col] for row in filtered]
        if values is not None:
            return values
        raise ValueError("Provide either values or rows")

    def batch_query(
        self,
        table_name: str,
        index_name: str,
        values: list[Any] | None = None,
        *,
        rows: list[dict[str, Any]] | None = None,
        gsi_col: str | None = None,
        sort_key_value: Any = None,
        sort_key_op: str = "=",
        filter_expr: str | None = None,
        filter_names: dict[str, str] | None = None,
        filter_values: dict[str, dict] | None = None,
        dynamodb: Any = None,
        max_workers: int | None = None,
        show_progress: bool = False,
        progress_desc: str | None = None,
        skip_statuses: list[str] | None = None,
        status_col: str = "row status",
    ) -> BatchQueryResult:
        effective_skip = skip_statuses if skip_statuses is not None else ["error", "warning"]
        resolved_values = self._resolve_batch_values(
            values, rows, gsi_col, effective_skip, status_col
        )
        table_name = self._resolve_table(table_name)
        init_client = self._client(dynamodb)
        pk_name, pk_type, sk_name, sk_type = self._resolve_gsi_keys(
            table_name, index_name, init_client
        )

        def _run(v: Any) -> tuple[Any, list[dict[str, Any]]]:
            client = self._client(dynamodb)
            kwargs = self._build_query_kwargs(
                table_name, index_name, v, pk_name, pk_type, sk_name, sk_type,
                sort_key_value=sort_key_value, sort_key_op=sort_key_op,
                filter_expr=filter_expr, filter_names=filter_names, filter_values=filter_values,
            )
            return v, self._run_query(kwargs, client)

        results: dict[Any, list[dict[str, Any]]] = {}
        errors: dict[Any, Exception] = {}

        _label = f"{progress_desc}: querying GSI" if progress_desc else "querying GSI"
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_run, v): v for v in resolved_values}
            for future in self._progress_iter(
                as_completed(futures),
                total=len(futures),
                desc=_label,
                show_progress=show_progress,
            ):
                v = futures[future]
                try:
                    _, items = future.result()
                    results[v] = items
                except Exception as e:
                    errors[v] = e

        batch_result = BatchQueryResult(results=results, errors=errors)
        self.rows = batch_result
        return batch_result

    def batch_count(
        self,
        table_name: str,
        index_name: str,
        values: list[Any] | None = None,
        *,
        rows: list[dict[str, Any]] | None = None,
        gsi_col: str | None = None,
        sort_key_value: Any = None,
        sort_key_op: str = "=",
        filter_expr: str | None = None,
        filter_names: dict[str, str] | None = None,
        filter_values: dict[str, dict] | None = None,
        dynamodb: Any = None,
        max_workers: int | None = None,
        show_progress: bool = False,
        progress_desc: str | None = None,
        skip_statuses: list[str] | None = None,
        status_col: str = "row status",
    ) -> BatchCountResult:
        effective_skip = skip_statuses if skip_statuses is not None else ["error", "warning"]
        resolved_values = self._resolve_batch_values(
            values, rows, gsi_col, effective_skip, status_col
        )
        table_name = self._resolve_table(table_name)
        init_client = self._client(dynamodb)
        pk_name, pk_type, sk_name, sk_type = self._resolve_gsi_keys(
            table_name, index_name, init_client
        )

        def _run(v: Any) -> tuple[Any, int]:
            client = self._client(dynamodb)
            kwargs = self._build_query_kwargs(
                table_name, index_name, v, pk_name, pk_type, sk_name, sk_type,
                sort_key_value=sort_key_value, sort_key_op=sort_key_op,
                filter_expr=filter_expr, filter_names=filter_names, filter_values=filter_values,
            )
            return v, self._run_count(kwargs, client)

        results: dict[Any, int] = {}
        errors: dict[Any, Exception] = {}

        _label = f"{progress_desc}: counting GSI" if progress_desc else "counting GSI"
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_run, v): v for v in resolved_values}
            for future in self._progress_iter(
                as_completed(futures),
                total=len(futures),
                desc=_label,
                show_progress=show_progress,
            ):
                v = futures[future]
                try:
                    _, total = future.result()
                    results[v] = total
                except Exception as e:
                    errors[v] = e

        batch_result = BatchCountResult(results=results, errors=errors)
        self.rows = batch_result
        return batch_result

    def batch_update_by_gsi(
        self,
        table_name: str,
        index_name: str,
        values: list[Any] | None = None,
        *,
        rows: list[dict[str, Any]] | None = None,
        gsi_col: str | None = None,
        update_attr: str,
        update_type: str,
        update_value: Any,
        increment: bool = False,
        incr_col: str | None = None,
        sort_key_value: Any = None,
        sort_key_op: str = "=",
        filter_expr: str | None = None,
        filter_names: dict[str, str] | None = None,
        filter_values: dict[str, dict] | None = None,
        commit: bool = False,
        dynamodb: Any = None,
        max_workers: int | None = None,
        show_progress: bool = False,
        progress_desc: str | None = None,
        skip_statuses: list[str] | None = None,
        status_col: str = "row status",
    ) -> BatchUpdateResult:
        if increment and incr_col is None:
            raise ValueError("incr_col is required when increment=True")
        if incr_col is not None and not increment:
            raise ValueError("incr_col requires increment=True")
        effective_skip = skip_statuses if skip_statuses is not None else ["error", "warning"]
        resolved_values = self._resolve_batch_values(
            values, rows, gsi_col, effective_skip, status_col
        )
        table_name = self._resolve_table(table_name)
        init_client = self._client(dynamodb)
        gsi_pk_name, gsi_pk_type, gsi_sk_name, gsi_sk_type = self._resolve_gsi_keys(
            table_name, index_name, init_client
        )
        tbl_pk_name, tbl_pk_type, tbl_sk_name, tbl_sk_type = self._resolve_table_keys(
            table_name, init_client
        )

        def _run(v: Any) -> tuple[Any, list[dict[str, Any]]]:
            client = self._client(dynamodb)
            gsi_kwargs = self._build_query_kwargs(
                table_name, index_name, v,
                gsi_pk_name, gsi_pk_type, gsi_sk_name, gsi_sk_type,
                sort_key_value=sort_key_value, sort_key_op=sort_key_op,
                filter_expr=filter_expr, filter_names=filter_names, filter_values=filter_values,
            )
            items = self._run_query(gsi_kwargs, client)

            item_results: list[dict[str, Any]] = []
            for item in items:
                tbl_pk_val = item.get(tbl_pk_name)
                row: dict[str, Any] = {tbl_pk_name: tbl_pk_val}
                if tbl_sk_name is not None:
                    row[tbl_sk_name] = item.get(tbl_sk_name)
                if not commit:
                    row["status"] = "dry_run"
                    item_results.append(row)
                    continue
                try:
                    key: dict[str, Any] = {tbl_pk_name: _ddb_val(tbl_pk_type, tbl_pk_val)}
                    if tbl_sk_name is not None and tbl_sk_type is not None:
                        key[tbl_sk_name] = _ddb_val(tbl_sk_type, item.get(tbl_sk_name))
                    upd_expr = "ADD #_upd :_updv" if increment else "SET #_upd = :_updv"
                    upd_attr = incr_col if increment else update_attr
                    client.update_item(
                        TableName=table_name,
                        Key=key,
                        UpdateExpression=upd_expr,
                        ExpressionAttributeNames={"#_upd": upd_attr},
                        ExpressionAttributeValues={":_updv": _ddb_val(update_type, update_value)},
                    )
                    row["status"] = "updated"
                except Exception as e:
                    row["status"] = "error"
                    row["message"] = str(e)
                item_results.append(row)

            return v, item_results

        upd_results: dict[Any, list[dict[str, Any]]] = {}
        errors: dict[Any, Exception] = {}

        _label = f"{progress_desc}: updating by GSI" if progress_desc else "updating by GSI"
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_run, v): v for v in resolved_values}
            for future in self._progress_iter(
                as_completed(futures),
                total=len(futures),
                desc=_label,
                show_progress=show_progress,
            ):
                v = futures[future]
                try:
                    _, item_results = future.result()
                    upd_results[v] = item_results
                except Exception as e:
                    errors[v] = e

        batch_result = BatchUpdateResult(results=upd_results, errors=errors)
        self.rows = batch_result
        return batch_result
