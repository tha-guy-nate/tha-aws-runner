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


# --- fetch_by_pk ---


def test_fetch_by_pk_happy(mock_ddb_client):
    mock_ddb_client.batch_get_item.return_value = {
        "Responses": {
            "my_table": [
                {"id": {"S": "pk1"}, "name": {"S": "Alice"}},
            ]
        },
        "UnprocessedKeys": {},
    }
    ddb = make_ddb(mock_ddb_client)
    result = ddb.fetch_by_pk("my_table", ["pk1", "pk2"], key_name="id", key_type="S")

    assert result["my_table"]["pk1"] == {"name": "Alice"}
    assert result["my_table"]["pk2"] == {"not_found": True}
    assert ddb.rows is result


def test_fetch_by_pk_with_fields(mock_ddb_client):
    mock_ddb_client.batch_get_item.return_value = {
        "Responses": {
            "my_table": [
                {"id": {"S": "pk1"}, "name": {"S": "Alice"}, "age": {"N": "30"}},
            ]
        },
        "UnprocessedKeys": {},
    }
    ddb = make_ddb(mock_ddb_client)
    result = ddb.fetch_by_pk(
        "my_table", ["pk1"], key_name="id", key_type="S", fields={"name": "S"}
    )
    assert result["my_table"]["pk1"] == {"name": "Alice"}


def test_fetch_by_pk_raises_on_client_error(mock_ddb_client):
    mock_ddb_client.batch_get_item.side_effect = _client_error("AccessDeniedException")
    ddb = make_ddb(mock_ddb_client)
    with pytest.raises(RuntimeError, match="DynamoDB batch fetch failed"):
        ddb.fetch_by_pk("my_table", ["pk1"], key_name="id", key_type="S")


# --- update_by_pk ---


def test_update_by_pk_happy(mock_ddb_client):
    mock_ddb_client.update_item.return_value = {"Attributes": {"id": {"S": "pk1"}}}
    ddb = make_ddb(mock_ddb_client)
    result = ddb.update_by_pk("my_table", "pk1", "id", "S", "status", "S", "active")
    assert result["status"] == "updated"
    assert ddb.rows is result


def test_update_by_pk_skipped_on_conditional_check(mock_ddb_client):
    mock_ddb_client.update_item.side_effect = _client_error("ConditionalCheckFailedException")
    ddb = make_ddb(mock_ddb_client)
    result = ddb.update_by_pk("my_table", "pk1", "id", "S", "status", "S", "active")
    assert result["status"] == "skipped"


def test_update_by_pk_to_ddb_attr_bool():
    ddb = ThaDdb()
    assert ddb.update_by_pk.__func__  # just verify it's accessible
    # test via a mock that captures the call args
    mock_client = MagicMock()
    mock_client.update_item.return_value = {"Attributes": {}}
    ddb._dynamodb = mock_client
    result = ddb.update_by_pk("t", "pk", "id", "S", "flag", "BOOL", True)
    assert result["status"] == "updated"


def test_update_by_pk_to_ddb_attr_invalid_bool():
    ddb = ThaDdb()
    mock_client = MagicMock()
    ddb._dynamodb = mock_client
    with pytest.raises(ValueError, match="BOOL only allows"):
        ddb.update_by_pk("t", "pk", "id", "S", "flag", "BOOL", "maybe")


# --- batch_put ---


def test_batch_put_happy(mock_ddb_client):
    mock_ddb_client.batch_write_item.return_value = {"UnprocessedItems": {}}
    ddb = make_ddb(mock_ddb_client)
    items = [{"id": {"S": f"pk{i}"}} for i in range(3)]
    result = ddb.batch_put("my_table", items, key_name="id")
    assert result["written"] == 3
    assert ddb.rows is result


def test_batch_put_chunks_at_25(mock_ddb_client):
    mock_ddb_client.batch_write_item.return_value = {"UnprocessedItems": {}}
    ddb = make_ddb(mock_ddb_client)
    items = [{"id": {"S": f"pk{i}"}} for i in range(30)]
    result = ddb.batch_put("my_table", items, key_name="id")
    assert result["written"] == 30
    assert mock_ddb_client.batch_write_item.call_count == 2


# --- delete_by_pk ---


def test_delete_by_pk_happy(mock_ddb_client):
    mock_ddb_client.delete_item.return_value = {}
    ddb = make_ddb(mock_ddb_client)
    result = ddb.delete_by_pk("my_table", "pk1", "id", "S")
    assert result["status"] == "deleted"
    assert ddb.rows is result


def test_delete_by_pk_skipped_when_not_exists(mock_ddb_client):
    mock_ddb_client.delete_item.side_effect = _client_error("ConditionalCheckFailedException")
    ddb = make_ddb(mock_ddb_client)
    result = ddb.delete_by_pk("my_table", "pk1", "id", "S")
    assert result["status"] == "skipped"
    assert result["message"] == "Item does not exist"
