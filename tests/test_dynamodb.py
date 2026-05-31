from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from tha_aws_runner.dynamodb import ThaDdb


def _client_error(code: str, message: str = "error") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": message}}, "operation")


def make_ddb(mock_client: MagicMock) -> ThaDdb:
    ddb = ThaDdb(region="us-east-1")
    ddb._dynamodb = mock_client
    return ddb


# --- fetch_by_pk (single item) ---


def test_fetch_by_pk_happy(mock_ddb_client):
    mock_ddb_client.get_item.return_value = {
        "Item": {"id": {"S": "pk1"}, "name": {"S": "Alice"}}
    }
    ddb = make_ddb(mock_ddb_client)
    result = ddb.fetch_by_pk("my_table", "pk1", key_name="id", key_type="S")
    assert result == {"name": "Alice"}
    assert ddb.rows is result


def test_fetch_by_pk_not_found(mock_ddb_client):
    mock_ddb_client.get_item.return_value = {}
    ddb = make_ddb(mock_ddb_client)
    result = ddb.fetch_by_pk("my_table", "missing", key_name="id", key_type="S")
    assert result == {"not_found": True}


def test_fetch_by_pk_not_found_with_fields(mock_ddb_client):
    mock_ddb_client.get_item.return_value = {}
    ddb = make_ddb(mock_ddb_client)
    result = ddb.fetch_by_pk(
        "my_table", "missing", key_name="id", key_type="S", fields={"name": "S"}
    )
    assert result == {"name": "not found"}


def test_fetch_by_pk_with_fields(mock_ddb_client):
    mock_ddb_client.get_item.return_value = {
        "Item": {"id": {"S": "pk1"}, "name": {"S": "Alice"}, "age": {"N": "30"}}
    }
    ddb = make_ddb(mock_ddb_client)
    result = ddb.fetch_by_pk(
        "my_table", "pk1", key_name="id", key_type="S", fields={"name": "S"}
    )
    assert result == {"name": "Alice"}


def test_fetch_by_pk_raises_on_client_error(mock_ddb_client):
    mock_ddb_client.get_item.side_effect = _client_error("AccessDeniedException")
    ddb = make_ddb(mock_ddb_client)
    with pytest.raises(RuntimeError, match="DynamoDB get_item failed"):
        ddb.fetch_by_pk("my_table", "pk1", key_name="id", key_type="S")


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
    result = ddb.batch_fetch_by_pk("my_table", ["pk1", "pk2"], key_name="id", key_type="S")

    assert result["my_table"]["pk1"] == {"name": "Alice"}
    assert result["my_table"]["pk2"] == {"not_found": True}
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
        "my_table", ["pk1"], key_name="id", key_type="S", fields={"name": "S"}
    )
    assert result["my_table"]["pk1"] == {"name": "Alice"}


def test_batch_fetch_by_pk_chunks_at_100(mock_ddb_client):
    mock_ddb_client.batch_get_item.return_value = {
        "Responses": {"my_table": []},
        "UnprocessedKeys": {},
    }
    ddb = make_ddb(mock_ddb_client)
    pks = [f"pk{i}" for i in range(101)]
    result = ddb.batch_fetch_by_pk("my_table", pks, key_name="id", key_type="S")
    assert mock_ddb_client.batch_get_item.call_count == 2
    first_keys = mock_ddb_client.batch_get_item.call_args_list[0].kwargs[
        "RequestItems"
    ]["my_table"]["Keys"]
    second_keys = mock_ddb_client.batch_get_item.call_args_list[1].kwargs[
        "RequestItems"
    ]["my_table"]["Keys"]
    assert len(first_keys) == 100
    assert len(second_keys) == 1
    assert all(result["my_table"][pk] == {"not_found": True} for pk in pks)


def test_batch_fetch_by_pk_threaded(mock_ddb_client):
    mock_ddb_client.batch_get_item.return_value = {
        "Responses": {
            "my_table": [{"id": {"S": f"pk{i}"}, "val": {"S": str(i)}} for i in range(201)]
        },
        "UnprocessedKeys": {},
    }
    ddb = make_ddb(mock_ddb_client)
    pks = [f"pk{i}" for i in range(201)]
    result = ddb.batch_fetch_by_pk(
        "my_table", pks, key_name="id", key_type="S",
        workers=3, dynamodb=mock_ddb_client,
    )
    assert mock_ddb_client.batch_get_item.call_count == 3
    assert all(result["my_table"][pk] != {"not_found": True} for pk in pks)
    assert ddb.rows is result


def test_batch_fetch_by_pk_error_in_chunk_returns_partial(mock_ddb_client):
    # chunk 1 succeeds, chunk 2 fails — chunk 1 data should still be returned
    def _side_effect(**kwargs):
        keys = kwargs["RequestItems"]["my_table"]["Keys"]
        if len(keys) == 100:
            return {"Responses": {"my_table": [{"id": {"S": f"pk{i}"}, "val": {"S": str(i)}} for i in range(100)]}, "UnprocessedKeys": {}}
        raise _client_error("AccessDeniedException", "Access denied")

    mock_ddb_client.batch_get_item.side_effect = _side_effect
    ddb = make_ddb(mock_ddb_client)
    pks = [f"pk{i}" for i in range(101)]
    result = ddb.batch_fetch_by_pk("my_table", pks, key_name="id", key_type="S")
    assert result["my_table"]["pk0"]["val"] == "0"
    assert result["my_table"]["pk100"] == {"error": "Access denied"}


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
    ddb._dynamodb = mock_client
    result = ddb.update_by_pk("t", "pk", "id", "S", "flag", "BOOL", True, commit=True)
    assert result["status"] == "updated"


def test_update_by_pk_to_ddb_attr_invalid_bool():
    ddb = ThaDdb()
    mock_client = MagicMock()
    ddb._dynamodb = mock_client
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
        "my_table", rows, "user_id", "id", "S", "status", "S", "status_col"
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
        "my_table", rows, "user_id", "id", "S", "status", "S", "status_col", commit=True
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
        "my_table", rows, "user_id", "id", "S", "status", "S", "status_col",
        workers=3, commit=True, dynamodb=mock_ddb_client,
    )
    assert len(result) == 6
    assert all(r["status"] == "updated" for r in result)
    assert mock_ddb_client.update_item.call_count == 6
    assert ddb.rows is result


# --- batch_delete_by_pk ---


def test_batch_delete_by_pk_dry_run(mock_ddb_client):
    ddb = make_ddb(mock_ddb_client)
    rows = [{"user_id": "pk1"}, {"user_id": "pk2"}]
    result = ddb.batch_delete_by_pk("my_table", rows, "user_id", "id", "S")
    assert result == [{"pk": "pk1", "status": "dry_run"}, {"pk": "pk2", "status": "dry_run"}]
    mock_ddb_client.delete_item.assert_not_called()
    assert ddb.rows is result


def test_batch_delete_by_pk_commit(mock_ddb_client):
    mock_ddb_client.delete_item.return_value = {}
    ddb = make_ddb(mock_ddb_client)
    rows = [{"user_id": "pk1"}, {"user_id": "pk2"}]
    result = ddb.batch_delete_by_pk("my_table", rows, "user_id", "id", "S", commit=True)
    assert len(result) == 2
    assert result[0]["status"] == "deleted"
    assert result[1]["status"] == "deleted"
    assert ddb.rows is result


def test_batch_delete_by_pk_threaded(mock_ddb_client):
    mock_ddb_client.delete_item.return_value = {}
    ddb = make_ddb(mock_ddb_client)
    rows = [{"user_id": f"pk{i}"} for i in range(6)]
    result = ddb.batch_delete_by_pk(
        "my_table", rows, "user_id", "id", "S",
        workers=3, commit=True, dynamodb=mock_ddb_client,
    )
    assert len(result) == 6
    assert all(r["status"] == "deleted" for r in result)
    assert mock_ddb_client.delete_item.call_count == 6
    assert ddb.rows is result


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
