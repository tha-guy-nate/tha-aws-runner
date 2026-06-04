from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from tha_aws_runner.dynamodb import ThaDdb


def _client_error(code: str, message: str = "error") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": message}}, "operation")


def make_ddb(mock_client: MagicMock) -> ThaDdb:
    ddb = ThaDdb(region="us-east-1")
    ddb._thread_local.dynamodb = mock_client
    return ddb


# --- fetch_by_pk (single item) ---


def test_fetch_by_pk_happy(mock_ddb_client):
    mock_ddb_client.get_item.return_value = {
        "Item": {"id": {"S": "pk1"}, "name": {"S": "Alice"}}
    }
    ddb = make_ddb(mock_ddb_client)
    result = ddb.fetch_by_pk("my_table", "pk1", key_name="id", key_type="S")
    assert result["status"] is None
    assert result["pk"] == "pk1"
    assert result["table"] == "my_table"
    assert result["data"] == {"name": "Alice"}
    assert ddb.rows is result


def test_fetch_by_pk_not_found(mock_ddb_client):
    mock_ddb_client.get_item.return_value = {}
    ddb = make_ddb(mock_ddb_client)
    result = ddb.fetch_by_pk("my_table", "missing", key_name="id", key_type="S")
    assert result["status"] == "error"
    assert result["pk"] == "missing"
    assert result["table"] == "my_table"
    assert result["data"] is None


def test_fetch_by_pk_not_found_with_fields(mock_ddb_client):
    mock_ddb_client.get_item.return_value = {}
    ddb = make_ddb(mock_ddb_client)
    result = ddb.fetch_by_pk(
        "my_table", "missing", key_name="id", key_type="S", fields={"name": "S"}
    )
    assert result["status"] == "error"
    assert result["data"] is None


def test_fetch_by_pk_with_fields(mock_ddb_client):
    mock_ddb_client.get_item.return_value = {
        "Item": {"id": {"S": "pk1"}, "name": {"S": "Alice"}, "age": {"N": "30"}}
    }
    ddb = make_ddb(mock_ddb_client)
    result = ddb.fetch_by_pk(
        "my_table", "pk1", key_name="id", key_type="S", fields={"name": "S"}
    )
    assert result["status"] is None
    assert result["data"] == {"name": "Alice"}


def test_fetch_by_pk_error_on_client_error(mock_ddb_client):
    mock_ddb_client.get_item.side_effect = _client_error("AccessDeniedException")
    ddb = make_ddb(mock_ddb_client)
    result = ddb.fetch_by_pk("my_table", "pk1", key_name="id", key_type="S")
    assert result["status"] == "error"
    assert result["pk"] == "pk1"
    assert result["table"] == "my_table"
    assert result["data"] is None
    assert "DynamoDB get_item failed" in result["message"]


# --- batch_fetch_by_pk ---


def test_batch_fetch_by_pk_happy(mock_ddb_client):
    mock_ddb_client.batch_get_item.return_value = {
        "Responses": {
            "my_table": [
                {"id": {"S": "pk1"}, "name": {"S": "Alice"}},
            ]
        },
        "UnprocessedKeys": {},
    }
    ddb = make_ddb(mock_ddb_client)
    rows = [{"ref": "pk1"}, {"ref": "pk2"}]
    result = ddb.batch_fetch_by_pk(rows, "ref", table_name="my_table", key_name="id", key_type="S")

    assert result["my_table"]["pk1"]["status"] is None
    assert result["my_table"]["pk1"]["pk"] == "pk1"
    assert result["my_table"]["pk1"]["table"] == "my_table"
    assert result["my_table"]["pk1"]["data"] == {"name": "Alice"}
    assert result["my_table"]["pk2"]["status"] == "error"
    assert result["my_table"]["pk2"]["data"] is None
    assert ddb.rows is result


def test_batch_fetch_by_pk_with_fields(mock_ddb_client):
    mock_ddb_client.batch_get_item.return_value = {
        "Responses": {
            "my_table": [
                {"id": {"S": "pk1"}, "name": {"S": "Alice"}, "age": {"N": "30"}},
            ]
        },
        "UnprocessedKeys": {},
    }
    ddb = make_ddb(mock_ddb_client)
    result = ddb.batch_fetch_by_pk(
        [{"ref": "pk1"}], "ref", table_name="my_table", key_name="id", key_type="S",
        fields={"name": "S"},
    )
    assert result["my_table"]["pk1"]["status"] is None
    assert result["my_table"]["pk1"]["data"] == {"name": "Alice"}


def test_batch_fetch_by_pk_chunks_at_100(mock_ddb_client):
    mock_ddb_client.batch_get_item.return_value = {
        "Responses": {"my_table": []},
        "UnprocessedKeys": {},
    }
    ddb = make_ddb(mock_ddb_client)
    rows = [{"ref": f"pk{i}"} for i in range(101)]
    result = ddb.batch_fetch_by_pk(rows, "ref", table_name="my_table", key_name="id", key_type="S")
    assert mock_ddb_client.batch_get_item.call_count == 2
    first_keys = mock_ddb_client.batch_get_item.call_args_list[0].kwargs[
        "RequestItems"
    ]["my_table"]["Keys"]
    second_keys = mock_ddb_client.batch_get_item.call_args_list[1].kwargs[
        "RequestItems"
    ]["my_table"]["Keys"]
    assert len(first_keys) == 100
    assert len(second_keys) == 1
    assert all(result["my_table"][f"pk{i}"]["status"] == "error" for i in range(101))


def test_batch_fetch_by_pk_threaded(mock_ddb_client):
    mock_ddb_client.batch_get_item.return_value = {
        "Responses": {
            "my_table": [{"id": {"S": f"pk{i}"}, "val": {"S": str(i)}} for i in range(201)]
        },
        "UnprocessedKeys": {},
    }
    ddb = make_ddb(mock_ddb_client)
    rows = [{"ref": f"pk{i}"} for i in range(201)]
    result = ddb.batch_fetch_by_pk(
        rows, "ref", table_name="my_table", key_name="id", key_type="S",
        workers=3, dynamodb=mock_ddb_client,
    )
    assert mock_ddb_client.batch_get_item.call_count == 3
    assert all(result["my_table"][f"pk{i}"]["status"] is None for i in range(201))
    assert ddb.rows is result


def test_batch_fetch_by_pk_error_in_chunk_returns_partial(mock_ddb_client):
    def _side_effect(**kwargs):
        keys = kwargs["RequestItems"]["my_table"]["Keys"]
        if len(keys) == 100:
            items = [{"id": {"S": f"pk{i}"}, "val": {"S": str(i)}} for i in range(100)]
            return {"Responses": {"my_table": items}, "UnprocessedKeys": {}}
        raise _client_error("AccessDeniedException", "Access denied")

    mock_ddb_client.batch_get_item.side_effect = _side_effect
    ddb = make_ddb(mock_ddb_client)
    rows = [{"ref": f"pk{i}"} for i in range(101)]
    result = ddb.batch_fetch_by_pk(rows, "ref", table_name="my_table", key_name="id", key_type="S")
    assert result["my_table"]["pk0"]["status"] is None
    assert result["my_table"]["pk0"]["data"]["val"] == "0"
    assert result["my_table"]["pk100"]["status"] == "error"
    assert result["my_table"]["pk100"]["message"] == "Access denied"
    assert result["my_table"]["pk100"]["data"] is None


def test_batch_fetch_by_pk_multi_table(mock_ddb_client):
    mock_ddb_client.batch_get_item.return_value = {
        "Responses": {
            "users": [{"id": {"S": "u1"}, "name": {"S": "Alice"}}],
            "orders": [{"id": {"S": "o1"}, "total": {"N": "42"}}],
        },
        "UnprocessedKeys": {},
    }
    ddb = make_ddb(mock_ddb_client)
    rows = [
        {"ref": "u1", "tbl": "users"},
        {"ref": "o1", "tbl": "orders"},
        {"ref": "u99", "tbl": "users"},
    ]
    result = ddb.batch_fetch_by_pk(rows, "ref", table_name_col="tbl", key_name="id", key_type="S")

    assert result["users"]["u1"]["status"] is None
    assert result["users"]["u1"]["data"] == {"name": "Alice"}
    assert result["orders"]["o1"]["status"] is None
    assert result["orders"]["o1"]["data"] == {"total": "42"}
    assert result["users"]["u99"]["status"] == "error"
    assert result["users"]["u99"]["message"] == "Item not found"

    call_args = mock_ddb_client.batch_get_item.call_args.kwargs["RequestItems"]
    assert set(call_args.keys()) == {"users", "orders"}


def test_batch_fetch_by_pk_deduplicates_rows(mock_ddb_client):
    mock_ddb_client.batch_get_item.return_value = {
        "Responses": {"my_table": [{"id": {"S": "pk1"}, "name": {"S": "Alice"}}]},
        "UnprocessedKeys": {},
    }
    ddb = make_ddb(mock_ddb_client)
    rows = [{"ref": "pk1"}, {"ref": "pk1"}, {"ref": "pk1"}]
    result = ddb.batch_fetch_by_pk(rows, "ref", table_name="my_table", key_name="id", key_type="S")
    assert mock_ddb_client.batch_get_item.call_count == 1
    keys_sent = mock_ddb_client.batch_get_item.call_args.kwargs["RequestItems"]["my_table"]["Keys"]
    assert len(keys_sent) == 1
    assert result["my_table"]["pk1"]["status"] is None


def test_batch_fetch_by_pk_requires_exactly_one_table_arg(mock_ddb_client):
    ddb = make_ddb(mock_ddb_client)
    with pytest.raises(ValueError, match="exactly one"):
        ddb.batch_fetch_by_pk([], "ref", key_name="id", key_type="S")
    with pytest.raises(ValueError, match="exactly one"):
        ddb.batch_fetch_by_pk(
            [], "ref", table_name="t", table_name_col="col", key_name="id", key_type="S"
        )


# --- update_by_pk ---


def test_update_by_pk_happy(mock_ddb_client):
    mock_ddb_client.update_item.return_value = {"Attributes": {"id": {"S": "pk1"}}}
    ddb = make_ddb(mock_ddb_client)
    result = ddb.update_by_pk("my_table", "pk1", "id", "S", "status", "S", "active", commit=True)
    assert result["status"] == "updated"
    assert ddb.rows is result


def test_update_by_pk_skipped_on_conditional_check(mock_ddb_client):
    mock_ddb_client.update_item.side_effect = _client_error("ConditionalCheckFailedException")
    ddb = make_ddb(mock_ddb_client)
    result = ddb.update_by_pk(
        "my_table", "pk1", "id", "S", "status", "S", "active", commit=True
    )
    assert result["status"] == "skipped"


def test_update_by_pk_to_ddb_attr_bool():
    ddb = ThaDdb()
    assert ddb.update_by_pk.__func__  # just verify it's accessible
    # test via a mock that captures the call args
    mock_client = MagicMock()
    mock_client.update_item.return_value = {"Attributes": {}}
    ddb._thread_local.dynamodb = mock_client
    result = ddb.update_by_pk("t", "pk", "id", "S", "flag", "BOOL", True, commit=True)
    assert result["status"] == "updated"


def test_update_by_pk_to_ddb_attr_invalid_bool():
    ddb = ThaDdb()
    mock_client = MagicMock()
    ddb._thread_local.dynamodb = mock_client
    with pytest.raises(ValueError, match="BOOL only allows"):
        ddb.update_by_pk("t", "pk", "id", "S", "flag", "BOOL", "maybe")


def test_update_by_pk_dry_run(mock_ddb_client):
    ddb = make_ddb(mock_ddb_client)
    result = ddb.update_by_pk("my_table", "pk1", "id", "S", "status", "S", "active")
    assert result == {"pk": "pk1", "status": "dry_run"}
    mock_ddb_client.update_item.assert_not_called()
    assert ddb.rows is result


def test_update_by_pk_dry_run_still_validates_type(mock_ddb_client):
    ddb = make_ddb(mock_ddb_client)
    with pytest.raises(ValueError, match="BOOL only allows"):
        ddb.update_by_pk("t", "pk", "id", "S", "flag", "BOOL", "maybe")


# --- batch_update_by_pk ---


def test_batch_update_by_pk_dry_run(mock_ddb_client):
    ddb = make_ddb(mock_ddb_client)
    rows = [
        {"user_id": "pk1", "status_col": "active"},
        {"user_id": "pk2", "status_col": "inactive"},
    ]
    result = ddb.batch_update_by_pk(
        rows, "user_id", "id", "S", "status", "S", "status_col", table_name="my_table"
    )
    assert result == [{"pk": "pk1", "status": "dry_run"}, {"pk": "pk2", "status": "dry_run"}]
    mock_ddb_client.update_item.assert_not_called()
    assert ddb.rows is result


def test_batch_update_by_pk_commit(mock_ddb_client):
    mock_ddb_client.update_item.return_value = {"Attributes": {"id": {"S": "pk1"}}}
    ddb = make_ddb(mock_ddb_client)
    rows = [
        {"user_id": "pk1", "status_col": "active"},
        {"user_id": "pk2", "status_col": "inactive"},
    ]
    result = ddb.batch_update_by_pk(
        rows, "user_id", "id", "S", "status", "S", "status_col",
        table_name="my_table", commit=True,
    )
    assert len(result) == 2
    assert result[0]["status"] == "updated"
    assert result[1]["status"] == "updated"
    assert ddb.rows is result


def test_batch_update_by_pk_threaded(mock_ddb_client):
    mock_ddb_client.update_item.return_value = {"Attributes": {"id": {"S": "pk"}}}
    ddb = make_ddb(mock_ddb_client)
    rows = [{"user_id": f"pk{i}", "status_col": "active"} for i in range(6)]
    result = ddb.batch_update_by_pk(
        rows, "user_id", "id", "S", "status", "S", "status_col",
        table_name="my_table", workers=3, commit=True, dynamodb=mock_ddb_client,
    )
    assert len(result) == 6
    assert all(r["status"] == "updated" for r in result)
    assert mock_ddb_client.update_item.call_count == 6
    assert ddb.rows is result


def test_batch_update_by_pk_table_name_col(mock_ddb_client):
    mock_ddb_client.update_item.return_value = {"Attributes": {"id": {"S": "pk1"}}}
    ddb = make_ddb(mock_ddb_client)
    rows = [
        {"user_id": "pk1", "status_col": "active", "tbl": "orders"},
        {"user_id": "pk2", "status_col": "inactive", "tbl": "users"},
    ]
    result = ddb.batch_update_by_pk(
        rows, "user_id", "id", "S", "status", "S", "status_col",
        table_name_col="tbl", commit=True,
    )
    assert len(result) == 2
    assert result[0]["status"] == "updated"
    assert result[1]["status"] == "updated"
    calls = mock_ddb_client.update_item.call_args_list
    assert calls[0][1]["TableName"] == "orders"
    assert calls[1][1]["TableName"] == "users"


def test_batch_update_by_pk_requires_table_name_or_col(mock_ddb_client):
    ddb = make_ddb(mock_ddb_client)
    rows = [{"user_id": "pk1", "status_col": "active"}]
    with pytest.raises(ValueError, match="table_name"):
        ddb.batch_update_by_pk(rows, "user_id", "id", "S", "status", "S", "status_col")


# --- batch_delete_by_pk ---


def test_batch_delete_by_pk_dry_run(mock_ddb_client):
    ddb = make_ddb(mock_ddb_client)
    rows = [{"user_id": "pk1"}, {"user_id": "pk2"}]
    result = ddb.batch_delete_by_pk(rows, "user_id", "id", "S", table_name="my_table")
    assert result == [{"pk": "pk1", "status": "dry_run"}, {"pk": "pk2", "status": "dry_run"}]
    mock_ddb_client.delete_item.assert_not_called()
    assert ddb.rows is result


def test_batch_delete_by_pk_commit(mock_ddb_client):
    mock_ddb_client.delete_item.return_value = {}
    ddb = make_ddb(mock_ddb_client)
    rows = [{"user_id": "pk1"}, {"user_id": "pk2"}]
    result = ddb.batch_delete_by_pk(rows, "user_id", "id", "S", table_name="my_table", commit=True)
    assert len(result) == 2
    assert result[0]["status"] == "deleted"
    assert result[1]["status"] == "deleted"
    assert ddb.rows is result


def test_batch_delete_by_pk_threaded(mock_ddb_client):
    mock_ddb_client.delete_item.return_value = {}
    ddb = make_ddb(mock_ddb_client)
    rows = [{"user_id": f"pk{i}"} for i in range(6)]
    result = ddb.batch_delete_by_pk(
        rows, "user_id", "id", "S",
        table_name="my_table", workers=3, commit=True, dynamodb=mock_ddb_client,
    )
    assert len(result) == 6
    assert all(r["status"] == "deleted" for r in result)
    assert mock_ddb_client.delete_item.call_count == 6
    assert ddb.rows is result


def test_batch_delete_by_pk_table_name_col(mock_ddb_client):
    mock_ddb_client.delete_item.return_value = {}
    ddb = make_ddb(mock_ddb_client)
    rows = [
        {"user_id": "pk1", "tbl": "orders"},
        {"user_id": "pk2", "tbl": "users"},
    ]
    result = ddb.batch_delete_by_pk(
        rows, "user_id", "id", "S", table_name_col="tbl", commit=True,
    )
    assert len(result) == 2
    assert result[0]["status"] == "deleted"
    assert result[1]["status"] == "deleted"
    calls = mock_ddb_client.delete_item.call_args_list
    assert calls[0][1]["TableName"] == "orders"
    assert calls[1][1]["TableName"] == "users"


def test_batch_delete_by_pk_requires_table_name_or_col(mock_ddb_client):
    ddb = make_ddb(mock_ddb_client)
    rows = [{"user_id": "pk1"}]
    with pytest.raises(ValueError, match="table_name"):
        ddb.batch_delete_by_pk(rows, "user_id", "id", "S")


# --- batch_write ---


def test_batch_write_dry_run(mock_ddb_client):
    ddb = make_ddb(mock_ddb_client)
    items = [{"id": {"S": f"pk{i}"}} for i in range(5)]
    result = ddb.batch_write("my_table", items)
    assert result == {"written": 5, "status": "dry_run"}
    mock_ddb_client.batch_write_item.assert_not_called()
    assert ddb.rows is result


def test_batch_write_happy(mock_ddb_client):
    mock_ddb_client.batch_write_item.return_value = {"UnprocessedItems": {}}
    ddb = make_ddb(mock_ddb_client)
    items = [{"id": {"S": f"pk{i}"}} for i in range(3)]
    result = ddb.batch_write("my_table", items, commit=True)
    assert result["written"] == 3
    assert ddb.rows is result


def test_batch_write_chunks_at_25(mock_ddb_client):
    mock_ddb_client.batch_write_item.return_value = {"UnprocessedItems": {}}
    ddb = make_ddb(mock_ddb_client)
    items = [{"id": {"S": f"pk{i}"}} for i in range(30)]
    result = ddb.batch_write("my_table", items, commit=True)
    assert result["written"] == 30
    assert mock_ddb_client.batch_write_item.call_count == 2


# --- delete_by_pk ---


def test_delete_by_pk_dry_run(mock_ddb_client):
    ddb = make_ddb(mock_ddb_client)
    result = ddb.delete_by_pk("my_table", "pk1", "id", "S")
    assert result == {"pk": "pk1", "status": "dry_run"}
    mock_ddb_client.delete_item.assert_not_called()
    assert ddb.rows is result


def test_delete_by_pk_happy(mock_ddb_client):
    mock_ddb_client.delete_item.return_value = {}
    ddb = make_ddb(mock_ddb_client)
    result = ddb.delete_by_pk("my_table", "pk1", "id", "S", commit=True)
    assert result["status"] == "deleted"
    assert ddb.rows is result


def test_delete_by_pk_skipped_when_not_exists(mock_ddb_client):
    mock_ddb_client.delete_item.side_effect = _client_error("ConditionalCheckFailedException")
    ddb = make_ddb(mock_ddb_client)
    result = ddb.delete_by_pk("my_table", "pk1", "id", "S", commit=True)
    assert result["status"] == "skipped"
    assert result["message"] == "Item does not exist"


# --- ARN resolution ---

_TABLE_ARN = "arn:aws:dynamodb:us-east-1:123456789012:table/my_table"


def test_resolve_table_plain():
    assert ThaDdb._resolve_table("my_table") == "my_table"


def test_resolve_table_arn():
    assert ThaDdb._resolve_table(_TABLE_ARN) == "my_table"


def test_fetch_by_pk_arn(mock_ddb_client):
    mock_ddb_client.get_item.return_value = {"Item": {"id": {"S": "pk1"}}}
    ddb = make_ddb(mock_ddb_client)
    result = ddb.fetch_by_pk(_TABLE_ARN, "pk1", key_name="id", key_type="S")
    assert result["table"] == "my_table"
    mock_ddb_client.get_item.assert_called_once()
    assert mock_ddb_client.get_item.call_args[1]["TableName"] == "my_table"


def test_update_by_pk_arn(mock_ddb_client):
    mock_ddb_client.update_item.return_value = {"Attributes": {}}
    ddb = make_ddb(mock_ddb_client)
    result = ddb.update_by_pk(
        _TABLE_ARN, "pk1", "id", "S", "status", "S", "active", commit=True
    )
    assert result["status"] == "updated"
    assert mock_ddb_client.update_item.call_args[1]["TableName"] == "my_table"


def test_delete_by_pk_arn(mock_ddb_client):
    mock_ddb_client.delete_item.return_value = {}
    ddb = make_ddb(mock_ddb_client)
    result = ddb.delete_by_pk(_TABLE_ARN, "pk1", "id", "S", commit=True)
    assert result["status"] == "deleted"
    assert mock_ddb_client.delete_item.call_args[1]["TableName"] == "my_table"


def test_batch_write_arn(mock_ddb_client):
    mock_ddb_client.batch_write_item.return_value = {"UnprocessedItems": {}}
    ddb = make_ddb(mock_ddb_client)
    result = ddb.batch_write(_TABLE_ARN, [{"id": {"S": "pk1"}}], commit=True)
    assert result["written"] == 1
    assert mock_ddb_client.batch_write_item.call_args[1]["RequestItems"] == {
        "my_table": [{"PutRequest": {"Item": {"id": {"S": "pk1"}}}}]
    }


def test_batch_fetch_by_pk_fixed_arn(mock_ddb_client):
    mock_ddb_client.batch_get_item.return_value = {
        "Responses": {"my_table": [{"id": {"S": "pk1"}, "name": {"S": "Alice"}}]},
        "UnprocessedKeys": {},
    }
    ddb = make_ddb(mock_ddb_client)
    rows = [{"id": "pk1"}]
    result = ddb.batch_fetch_by_pk(rows, "id", table_name=_TABLE_ARN, key_name="id", key_type="S")
    assert "my_table" in result
    assert result["my_table"]["pk1"]["status"] is None
