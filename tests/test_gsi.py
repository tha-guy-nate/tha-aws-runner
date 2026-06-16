from unittest.mock import MagicMock

import pytest

from tha_aws_runner.gsi import BatchCountResult, BatchQueryResult, ThaGsi

# GSI with partition key only
_TABLE_DESC: dict = {
    "TableName": "users",
    "AttributeDefinitions": [
        {"AttributeName": "user_id", "AttributeType": "S"},
        {"AttributeName": "email", "AttributeType": "S"},
    ],
    "GlobalSecondaryIndexes": [
        {
            "IndexName": "email-index",
            "KeySchema": [{"AttributeName": "email", "KeyType": "HASH"}],
        },
    ],
}

# GSI with partition key (N) and sort key (S)
_SK_TABLE_DESC: dict = {
    "TableName": "orders",
    "AttributeDefinitions": [
        {"AttributeName": "user_id", "AttributeType": "S"},
        {"AttributeName": "created_at", "AttributeType": "S"},
    ],
    "GlobalSecondaryIndexes": [
        {
            "IndexName": "user-date-index",
            "KeySchema": [
                {"AttributeName": "user_id", "KeyType": "HASH"},
                {"AttributeName": "created_at", "KeyType": "RANGE"},
            ],
        },
    ],
}

# GSI with numeric partition key
_NUMERIC_TABLE_DESC: dict = {
    "TableName": "metrics",
    "AttributeDefinitions": [
        {"AttributeName": "metric_id", "AttributeType": "S"},
        {"AttributeName": "customer_id", "AttributeType": "N"},
    ],
    "GlobalSecondaryIndexes": [
        {
            "IndexName": "customer-index",
            "KeySchema": [{"AttributeName": "customer_id", "KeyType": "HASH"}],
        },
    ],
}


def _client(table_desc: dict, query_pages: list) -> MagicMock:
    mock = MagicMock()
    mock.describe_table.return_value = {"Table": table_desc}
    mock.query.side_effect = query_pages
    return mock


@pytest.fixture
def gsi() -> ThaGsi:
    return ThaGsi()


# --- basic query ---


def test_query_basic(gsi: ThaGsi) -> None:
    c = _client(
        _TABLE_DESC,
        [{"Items": [{"email": {"S": "a@x.com"}, "name": {"S": "Alice"}}]}],
    )
    result = gsi.query("users", "email-index", "a@x.com", dynamodb=c)
    assert result == [{"email": "a@x.com", "name": "Alice"}]


def test_query_sets_rows(gsi: ThaGsi) -> None:
    c = _client(_TABLE_DESC, [{"Items": [{"email": {"S": "a@x.com"}}]}])
    result = gsi.query("users", "email-index", "a@x.com", dynamodb=c)
    assert gsi.rows is result


def test_query_empty(gsi: ThaGsi) -> None:
    c = _client(_TABLE_DESC, [{"Items": []}])
    assert gsi.query("users", "email-index", "nobody@x.com", dynamodb=c) == []


def test_query_pagination(gsi: ThaGsi) -> None:
    page1 = {
        "Items": [{"email": {"S": "a@x.com"}, "user_id": {"S": "u1"}}],
        "LastEvaluatedKey": {"email": {"S": "a@x.com"}},
    }
    page2 = {"Items": [{"email": {"S": "b@x.com"}, "user_id": {"S": "u2"}}]}
    c = _client(_TABLE_DESC, [page1, page2])
    result = gsi.query("users", "email-index", "a@x.com", dynamodb=c)
    assert len(result) == 2
    assert result[0]["user_id"] == "u1"
    assert result[1]["user_id"] == "u2"
    assert c.query.call_count == 2
    assert "ExclusiveStartKey" in c.query.call_args_list[1].kwargs


def test_query_expression_uses_reserved_placeholders(gsi: ThaGsi) -> None:
    c = _client(_TABLE_DESC, [{"Items": []}])
    gsi.query("users", "email-index", "a@x.com", dynamodb=c)
    kwargs = c.query.call_args.kwargs
    assert kwargs["ExpressionAttributeNames"] == {"#_pk": "email"}
    assert kwargs["ExpressionAttributeValues"] == {":_pkv": {"S": "a@x.com"}}


def test_query_numeric_pk(gsi: ThaGsi) -> None:
    c = _client(
        _NUMERIC_TABLE_DESC,
        [{"Items": [{"customer_id": {"N": "42"}, "metric_id": {"S": "m1"}}]}],
    )
    result = gsi.query("metrics", "customer-index", 42, dynamodb=c)
    assert result == [{"customer_id": "42", "metric_id": "m1"}]
    assert c.query.call_args.kwargs["ExpressionAttributeValues"] == {":_pkv": {"N": "42"}}


def test_query_unknown_gsi_raises(gsi: ThaGsi) -> None:
    c = _client(_TABLE_DESC, [])
    with pytest.raises(ValueError, match="GSI 'bad-index' not found"):
        gsi.query("users", "bad-index", "x", dynamodb=c)


def test_describe_table_cached(gsi: ThaGsi) -> None:
    c = _client(_TABLE_DESC, [{"Items": []}, {"Items": []}])
    gsi.query("users", "email-index", "a@x.com", dynamodb=c)
    gsi.query("users", "email-index", "b@x.com", dynamodb=c)
    assert c.describe_table.call_count == 1


def test_arn_table_resolved(gsi: ThaGsi) -> None:
    arn = "arn:aws:dynamodb:us-east-1:123456789012:table/users"
    c = _client(_TABLE_DESC, [{"Items": []}])
    gsi.query(arn, "email-index", "a@x.com", dynamodb=c)
    c.describe_table.assert_called_once_with(TableName="users")


def test_resolve_gsi_keys_no_hash_raises(gsi: ThaGsi) -> None:
    desc = {
        "TableName": "t",
        "AttributeDefinitions": [{"AttributeName": "x", "AttributeType": "S"}],
        "GlobalSecondaryIndexes": [
            {"IndexName": "x-index", "KeySchema": [{"AttributeName": "x", "KeyType": "RANGE"}]},
        ],
    }
    c = MagicMock()
    c.describe_table.return_value = {"Table": desc}
    with pytest.raises(ValueError, match="No HASH key found"):
        gsi.query("t", "x-index", "v", dynamodb=c)


def test_resolve_gsi_keys_missing_attr_def_raises(gsi: ThaGsi) -> None:
    desc = {
        "TableName": "t",
        "AttributeDefinitions": [],
        "GlobalSecondaryIndexes": [
            {"IndexName": "x-index", "KeySchema": [{"AttributeName": "x", "KeyType": "HASH"}]},
        ],
    }
    c = MagicMock()
    c.describe_table.return_value = {"Table": desc}
    with pytest.raises(ValueError, match="AttributeDefinition not found for 'x'"):
        gsi.query("t", "x-index", "v", dynamodb=c)


# --- sort key ---


def test_query_sort_key_eq(gsi: ThaGsi) -> None:
    c = _client(_SK_TABLE_DESC, [{"Items": []}])
    gsi.query(
        "orders", "user-date-index", "u1", sort_key_value="2024-01-01", sort_key_op="=", dynamodb=c
    )
    kce = c.query.call_args.kwargs["KeyConditionExpression"]
    assert kce == "#_pk = :_pkv AND #_sk = :_skv"


def test_query_sort_key_gte(gsi: ThaGsi) -> None:
    c = _client(_SK_TABLE_DESC, [{"Items": []}])
    gsi.query(
        "orders", "user-date-index", "u1", sort_key_value="2024-01-01", sort_key_op=">=", dynamodb=c
    )
    kw = c.query.call_args.kwargs
    assert "#_pk = :_pkv AND #_sk >= :_skv" == kw["KeyConditionExpression"]
    assert kw["ExpressionAttributeValues"][":_skv"] == {"S": "2024-01-01"}
    assert kw["ExpressionAttributeNames"]["#_sk"] == "created_at"


def test_query_sort_key_between(gsi: ThaGsi) -> None:
    c = _client(_SK_TABLE_DESC, [{"Items": []}])
    gsi.query(
        "orders",
        "user-date-index",
        "u1",
        sort_key_value=("2024-01-01", "2024-12-31"),
        sort_key_op="between",
        dynamodb=c,
    )
    kw = c.query.call_args.kwargs
    assert kw["KeyConditionExpression"] == "#_pk = :_pkv AND #_sk BETWEEN :_skv1 AND :_skv2"
    assert kw["ExpressionAttributeValues"][":_skv1"] == {"S": "2024-01-01"}
    assert kw["ExpressionAttributeValues"][":_skv2"] == {"S": "2024-12-31"}


def test_query_sort_key_begins_with(gsi: ThaGsi) -> None:
    c = _client(_SK_TABLE_DESC, [{"Items": []}])
    gsi.query(
        "orders",
        "user-date-index",
        "u1",
        sort_key_value="2024",
        sort_key_op="begins_with",
        dynamodb=c,
    )
    kce = c.query.call_args.kwargs["KeyConditionExpression"]
    assert kce == "#_pk = :_pkv AND begins_with(#_sk, :_skv)"


def test_query_sort_key_on_gsi_without_sk_raises(gsi: ThaGsi) -> None:
    c = _client(_TABLE_DESC, [])
    with pytest.raises(ValueError, match="has no sort key"):
        gsi.query("users", "email-index", "a@x.com", sort_key_value="val", dynamodb=c)


def test_query_invalid_sort_key_op_raises(gsi: ThaGsi) -> None:
    c = _client(_SK_TABLE_DESC, [])
    with pytest.raises(ValueError, match="Invalid sort_key_op"):
        gsi.query(
            "orders", "user-date-index", "u1", sort_key_value="2024", sort_key_op="LIKE", dynamodb=c
        )


def test_query_between_non_tuple_raises(gsi: ThaGsi) -> None:
    c = _client(_SK_TABLE_DESC, [])
    with pytest.raises(ValueError, match="2-element tuple"):
        gsi.query(
            "orders",
            "user-date-index",
            "u1",
            sort_key_value="2024-01-01",
            sort_key_op="between",
            dynamodb=c,
        )


def test_query_between_wrong_length_raises(gsi: ThaGsi) -> None:
    c = _client(_SK_TABLE_DESC, [])
    with pytest.raises(ValueError, match="2-element tuple"):
        gsi.query(
            "orders",
            "user-date-index",
            "u1",
            sort_key_value=("a", "b", "c"),
            sort_key_op="between",
            dynamodb=c,
        )


# --- filter expression ---


def test_query_filter_expr(gsi: ThaGsi) -> None:
    c = _client(_TABLE_DESC, [{"Items": []}])
    gsi.query(
        "users",
        "email-index",
        "a@x.com",
        filter_expr="#s = :status",
        filter_names={"#s": "status"},
        filter_values={":status": {"S": "active"}},
        dynamodb=c,
    )
    kw = c.query.call_args.kwargs
    assert kw["FilterExpression"] == "#s = :status"
    assert kw["ExpressionAttributeNames"]["#s"] == "status"
    assert kw["ExpressionAttributeValues"][":status"] == {"S": "active"}


def test_query_filter_expr_without_names(gsi: ThaGsi) -> None:
    c = _client(_TABLE_DESC, [{"Items": []}])
    gsi.query(
        "users",
        "email-index",
        "a@x.com",
        filter_expr="attribute_exists(deleted_at)",
        dynamodb=c,
    )
    kw = c.query.call_args.kwargs
    assert kw["FilterExpression"] == "attribute_exists(deleted_at)"
    assert "#s" not in kw["ExpressionAttributeNames"]


def test_query_filter_values_without_expr_raises(gsi: ThaGsi) -> None:
    c = _client(_TABLE_DESC, [])
    with pytest.raises(ValueError, match="filter_values requires filter_expr"):
        gsi.query(
            "users", "email-index", "a@x.com", filter_values={":s": {"S": "active"}}, dynamodb=c
        )


def test_query_filter_reserved_placeholder_raises(gsi: ThaGsi) -> None:
    c = _client(_TABLE_DESC, [])
    with pytest.raises(ValueError, match="reserved placeholders"):
        gsi.query(
            "users",
            "email-index",
            "a@x.com",
            filter_expr="#_pk = :x",
            filter_names={"#_pk": "something"},
            filter_values={":x": {"S": "v"}},
            dynamodb=c,
        )


def test_query_sort_key_and_filter_combined(gsi: ThaGsi) -> None:
    c = _client(_SK_TABLE_DESC, [{"Items": []}])
    gsi.query(
        "orders",
        "user-date-index",
        "u1",
        sort_key_value="2024-01-01",
        sort_key_op=">=",
        filter_expr="#amt > :min",
        filter_names={"#amt": "amount"},
        filter_values={":min": {"N": "100"}},
        dynamodb=c,
    )
    kw = c.query.call_args.kwargs
    assert "#_pk = :_pkv AND #_sk >= :_skv" == kw["KeyConditionExpression"]
    assert kw["FilterExpression"] == "#amt > :min"
    assert kw["ExpressionAttributeNames"]["#amt"] == "amount"
    assert kw["ExpressionAttributeValues"][":min"] == {"N": "100"}


# --- count ---


def test_count_basic(gsi: ThaGsi) -> None:
    c = _client(_TABLE_DESC, [{"Count": 7}])
    assert gsi.count("users", "email-index", "a@x.com", dynamodb=c) == 7


def test_count_sets_rows(gsi: ThaGsi) -> None:
    c = _client(_TABLE_DESC, [{"Count": 3}])
    result = gsi.count("users", "email-index", "a@x.com", dynamodb=c)
    assert gsi.rows == 3
    assert gsi.rows is result


def test_count_uses_select_count(gsi: ThaGsi) -> None:
    c = _client(_TABLE_DESC, [{"Count": 0}])
    gsi.count("users", "email-index", "a@x.com", dynamodb=c)
    assert c.query.call_args.kwargs["Select"] == "COUNT"


def test_count_pagination(gsi: ThaGsi) -> None:
    page1 = {"Count": 10, "LastEvaluatedKey": {"email": {"S": "z@x.com"}}}
    page2 = {"Count": 4}
    c = _client(_TABLE_DESC, [page1, page2])
    assert gsi.count("users", "email-index", "a@x.com", dynamodb=c) == 14
    assert c.query.call_count == 2


def test_count_with_sort_key(gsi: ThaGsi) -> None:
    c = _client(_SK_TABLE_DESC, [{"Count": 5}])
    result = gsi.count(
        "orders", "user-date-index", "u1", sort_key_value="2024-01-01", sort_key_op=">=", dynamodb=c
    )
    assert result == 5
    kw = c.query.call_args.kwargs
    assert "#_pk = :_pkv AND #_sk >= :_skv" == kw["KeyConditionExpression"]
    assert kw["Select"] == "COUNT"


def test_count_with_filter(gsi: ThaGsi) -> None:
    c = _client(_TABLE_DESC, [{"Count": 2}])
    gsi.count(
        "users",
        "email-index",
        "a@x.com",
        filter_expr="#s = :status",
        filter_names={"#s": "status"},
        filter_values={":status": {"S": "active"}},
        dynamodb=c,
    )
    kw = c.query.call_args.kwargs
    assert kw["FilterExpression"] == "#s = :status"
    assert kw["Select"] == "COUNT"


# --- batch_query ---


def _client_fn(table_desc: dict) -> MagicMock:
    """Client whose query response is driven by the :_pkv value."""
    mock = MagicMock()
    mock.describe_table.return_value = {"Table": table_desc}

    def _query(**kwargs: object) -> dict:
        pk_val = next(iter(kwargs["ExpressionAttributeValues"][":_pkv"].values()))  # type: ignore[index]
        return {"Items": [{"email": {"S": str(pk_val)}, "user_id": {"S": f"u-{pk_val}"}}]}

    mock.query.side_effect = _query
    return mock


def _client_fn_with_error(table_desc: dict, error_value: str) -> MagicMock:
    mock = MagicMock()
    mock.describe_table.return_value = {"Table": table_desc}

    def _query(**kwargs: object) -> dict:
        pk_val = next(iter(kwargs["ExpressionAttributeValues"][":_pkv"].values()))  # type: ignore[index]
        if str(pk_val) == error_value:
            raise RuntimeError("DDB error")
        return {"Items": [{"email": {"S": str(pk_val)}}]}

    mock.query.side_effect = _query
    return mock


def test_batch_query_basic(gsi: ThaGsi) -> None:
    c = _client_fn(_TABLE_DESC)
    result = gsi.batch_query("users", "email-index", ["a@x.com", "b@x.com"], dynamodb=c)
    assert isinstance(result, BatchQueryResult)
    assert set(result.results) == {"a@x.com", "b@x.com"}
    assert result.errors == {}
    assert result.results["a@x.com"] == [{"email": "a@x.com", "user_id": "u-a@x.com"}]


def test_batch_query_sets_rows(gsi: ThaGsi) -> None:
    c = _client_fn(_TABLE_DESC)
    result = gsi.batch_query("users", "email-index", ["a@x.com"], dynamodb=c)
    assert gsi.rows is result


def test_batch_query_empty_values(gsi: ThaGsi) -> None:
    c = _client_fn(_TABLE_DESC)
    result = gsi.batch_query("users", "email-index", [], dynamodb=c)
    assert result.results == {}
    assert result.errors == {}


def test_batch_query_partial_failure(gsi: ThaGsi) -> None:
    c = _client_fn_with_error(_TABLE_DESC, "bad@x.com")
    result = gsi.batch_query(
        "users", "email-index", ["a@x.com", "bad@x.com", "b@x.com"], dynamodb=c
    )
    assert "a@x.com" in result.results
    assert "b@x.com" in result.results
    assert "bad@x.com" in result.errors
    assert isinstance(result.errors["bad@x.com"], RuntimeError)


def test_batch_query_table_desc_cached(gsi: ThaGsi) -> None:
    c = _client_fn(_TABLE_DESC)
    gsi.batch_query("users", "email-index", ["a@x.com", "b@x.com", "c@x.com"], dynamodb=c)
    assert c.describe_table.call_count == 1


def test_batch_query_bad_index_raises(gsi: ThaGsi) -> None:
    c = _client_fn(_TABLE_DESC)
    with pytest.raises(ValueError, match="GSI 'bad-index' not found"):
        gsi.batch_query("users", "bad-index", ["a@x.com"], dynamodb=c)


# --- batch_count ---


def _count_client_fn(table_desc: dict) -> MagicMock:
    mock = MagicMock()
    mock.describe_table.return_value = {"Table": table_desc}

    def _query(**kwargs: object) -> dict:
        pk_val = next(iter(kwargs["ExpressionAttributeValues"][":_pkv"].values()))  # type: ignore[index]
        return {"Count": len(str(pk_val))}

    mock.query.side_effect = _query
    return mock


def _count_client_fn_with_error(table_desc: dict, error_value: str) -> MagicMock:
    mock = MagicMock()
    mock.describe_table.return_value = {"Table": table_desc}

    def _query(**kwargs: object) -> dict:
        pk_val = next(iter(kwargs["ExpressionAttributeValues"][":_pkv"].values()))  # type: ignore[index]
        if str(pk_val) == error_value:
            raise RuntimeError("DDB error")
        return {"Count": 1}

    mock.query.side_effect = _query
    return mock


def test_batch_count_basic(gsi: ThaGsi) -> None:
    c = _count_client_fn(_TABLE_DESC)
    result = gsi.batch_count("users", "email-index", ["ab", "abc"], dynamodb=c)
    assert isinstance(result, BatchCountResult)
    assert result.results["ab"] == 2
    assert result.results["abc"] == 3
    assert result.errors == {}


def test_batch_count_sets_rows(gsi: ThaGsi) -> None:
    c = _count_client_fn(_TABLE_DESC)
    result = gsi.batch_count("users", "email-index", ["a@x.com"], dynamodb=c)
    assert gsi.rows is result


def test_batch_count_empty_values(gsi: ThaGsi) -> None:
    c = _count_client_fn(_TABLE_DESC)
    result = gsi.batch_count("users", "email-index", [], dynamodb=c)
    assert result.results == {}
    assert result.errors == {}


def test_batch_count_partial_failure(gsi: ThaGsi) -> None:
    c = _count_client_fn_with_error(_TABLE_DESC, "bad")
    result = gsi.batch_count("users", "email-index", ["ok", "bad"], dynamodb=c)
    assert "ok" in result.results
    assert "bad" in result.errors
    assert isinstance(result.errors["bad"], RuntimeError)


def test_batch_count_uses_select_count(gsi: ThaGsi) -> None:
    mock = MagicMock()
    mock.describe_table.return_value = {"Table": _TABLE_DESC}
    mock.query.return_value = {"Count": 0}
    gsi.batch_count("users", "email-index", ["a@x.com"], dynamodb=mock)
    assert mock.query.call_args.kwargs["Select"] == "COUNT"


def test_batch_query_with_rows(gsi: ThaGsi) -> None:
    c = _client_fn(_TABLE_DESC)
    rows = [{"email": "a@x.com", "name": "Alice"}, {"email": "b@x.com", "name": "Bob"}]
    result = gsi.batch_query("users", "email-index", rows=rows, gsi_col="email", dynamodb=c)
    assert set(result.results) == {"a@x.com", "b@x.com"}
    assert result.errors == {}


def test_batch_query_rows_without_pk_col_raises(gsi: ThaGsi) -> None:
    c = _client_fn(_TABLE_DESC)
    with pytest.raises(ValueError, match="gsi_col is required"):
        gsi.batch_query("users", "email-index", rows=[{"email": "a@x.com"}], dynamodb=c)


def test_batch_query_both_values_and_rows_raises(gsi: ThaGsi) -> None:
    c = _client_fn(_TABLE_DESC)
    with pytest.raises(ValueError, match="not both"):
        gsi.batch_query(
            "users",
            "email-index",
            ["a@x.com"],
            rows=[{"email": "a@x.com"}],
            gsi_col="email",
            dynamodb=c,
        )


def test_batch_query_neither_values_nor_rows_raises(gsi: ThaGsi) -> None:
    c = _client_fn(_TABLE_DESC)
    with pytest.raises(ValueError, match="Provide either values or rows"):
        gsi.batch_query("users", "email-index", dynamodb=c)


def test_batch_query_show_progress(gsi: ThaGsi) -> None:
    c = _client_fn(_TABLE_DESC)
    result = gsi.batch_query(
        "users",
        "email-index",
        ["a@x.com", "b@x.com"],
        dynamodb=c,
        show_progress=True,
        progress_desc="querying",
    )
    assert set(result.results) == {"a@x.com", "b@x.com"}
    assert result.errors == {}


def test_batch_count_with_rows(gsi: ThaGsi) -> None:
    c = _count_client_fn(_TABLE_DESC)
    rows = [{"status": "ab", "extra": 1}, {"status": "abc", "extra": 2}]
    result = gsi.batch_count("users", "email-index", rows=rows, gsi_col="status", dynamodb=c)
    assert result.results["ab"] == 2
    assert result.results["abc"] == 3
    assert result.errors == {}


def test_batch_count_rows_without_pk_col_raises(gsi: ThaGsi) -> None:
    c = _count_client_fn(_TABLE_DESC)
    with pytest.raises(ValueError, match="gsi_col is required"):
        gsi.batch_count("users", "email-index", rows=[{"status": "ab"}], dynamodb=c)


def test_batch_count_both_values_and_rows_raises(gsi: ThaGsi) -> None:
    c = _count_client_fn(_TABLE_DESC)
    with pytest.raises(ValueError, match="not both"):
        gsi.batch_count(
            "users",
            "email-index",
            ["ab"],
            rows=[{"status": "ab"}],
            gsi_col="status",
            dynamodb=c,
        )


def test_batch_count_neither_values_nor_rows_raises(gsi: ThaGsi) -> None:
    c = _count_client_fn(_TABLE_DESC)
    with pytest.raises(ValueError, match="Provide either values or rows"):
        gsi.batch_count("users", "email-index", dynamodb=c)


def test_batch_count_show_progress(gsi: ThaGsi) -> None:
    c = _count_client_fn(_TABLE_DESC)
    result = gsi.batch_count(
        "users",
        "email-index",
        ["ab", "abc"],
        dynamodb=c,
        show_progress=True,
        progress_desc="counting",
    )
    assert result.results["ab"] == 2
    assert result.results["abc"] == 3
    assert result.errors == {}


# --- update_by_gsi ---

# Table with PK only, GSI on status
_UPD_TABLE_DESC: dict = {
    "TableName": "orders",
    "AttributeDefinitions": [
        {"AttributeName": "order_id", "AttributeType": "S"},
        {"AttributeName": "status", "AttributeType": "S"},
    ],
    "KeySchema": [
        {"AttributeName": "order_id", "KeyType": "HASH"},
    ],
    "GlobalSecondaryIndexes": [
        {
            "IndexName": "status-index",
            "KeySchema": [{"AttributeName": "status", "KeyType": "HASH"}],
        },
    ],
}

# Table with PK + sort key, GSI on type
_UPD_TABLE_WITH_SK_DESC: dict = {
    "TableName": "events",
    "AttributeDefinitions": [
        {"AttributeName": "user_id", "AttributeType": "S"},
        {"AttributeName": "created_at", "AttributeType": "S"},
        {"AttributeName": "type", "AttributeType": "S"},
    ],
    "KeySchema": [
        {"AttributeName": "user_id", "KeyType": "HASH"},
        {"AttributeName": "created_at", "KeyType": "RANGE"},
    ],
    "GlobalSecondaryIndexes": [
        {
            "IndexName": "type-index",
            "KeySchema": [{"AttributeName": "type", "KeyType": "HASH"}],
        },
    ],
}


def _upd_client(table_desc: dict, gsi_items: list[dict]) -> MagicMock:
    mock = MagicMock()
    mock.describe_table.return_value = {"Table": table_desc}
    mock.query.return_value = {"Items": gsi_items}
    mock.update_item.return_value = {}
    return mock


def test_update_by_gsi_dry_run(gsi: ThaGsi) -> None:
    c = _upd_client(
        _UPD_TABLE_DESC,
        [{"order_id": {"S": "o1"}, "status": {"S": "PENDING"}}],
    )
    result = gsi.update_by_gsi(
        "orders", "status-index", "PENDING", "status", "S", "SHIPPED", dynamodb=c
    )
    assert result == [{"order_id": "o1", "status": "dry_run"}]
    c.update_item.assert_not_called()


def test_update_by_gsi_commit(gsi: ThaGsi) -> None:
    c = _upd_client(
        _UPD_TABLE_DESC,
        [{"order_id": {"S": "o1"}, "status": {"S": "PENDING"}}],
    )
    result = gsi.update_by_gsi(
        "orders",
        "status-index",
        "PENDING",
        "status",
        "S",
        "SHIPPED",
        commit=True,
        dynamodb=c,
    )
    assert result == [{"order_id": "o1", "status": "updated"}]
    c.update_item.assert_called_once_with(
        TableName="orders",
        Key={"order_id": {"S": "o1"}},
        UpdateExpression="SET #_upd = :_updv",
        ExpressionAttributeNames={"#_upd": "status"},
        ExpressionAttributeValues={":_updv": {"S": "SHIPPED"}},
    )


def test_update_by_gsi_multiple_items(gsi: ThaGsi) -> None:
    c = _upd_client(
        _UPD_TABLE_DESC,
        [
            {"order_id": {"S": "o1"}, "status": {"S": "PENDING"}},
            {"order_id": {"S": "o2"}, "status": {"S": "PENDING"}},
        ],
    )
    result = gsi.update_by_gsi(
        "orders",
        "status-index",
        "PENDING",
        "status",
        "S",
        "SHIPPED",
        commit=True,
        dynamodb=c,
    )
    assert len(result) == 2
    assert all(r["status"] == "updated" for r in result)
    assert c.update_item.call_count == 2


def test_update_by_gsi_empty(gsi: ThaGsi) -> None:
    c = _upd_client(_UPD_TABLE_DESC, [])
    result = gsi.update_by_gsi(
        "orders",
        "status-index",
        "MISSING",
        "status",
        "S",
        "SHIPPED",
        commit=True,
        dynamodb=c,
    )
    assert result == []
    c.update_item.assert_not_called()


def test_update_by_gsi_sets_rows(gsi: ThaGsi) -> None:
    c = _upd_client(
        _UPD_TABLE_DESC,
        [{"order_id": {"S": "o1"}, "status": {"S": "PENDING"}}],
    )
    result = gsi.update_by_gsi(
        "orders", "status-index", "PENDING", "status", "S", "SHIPPED", dynamodb=c
    )
    assert gsi.rows is result


def test_update_by_gsi_with_table_sort_key(gsi: ThaGsi) -> None:
    c = _upd_client(
        _UPD_TABLE_WITH_SK_DESC,
        [{"user_id": {"S": "u1"}, "created_at": {"S": "2024-01-01"}, "type": {"S": "click"}}],
    )
    result = gsi.update_by_gsi(
        "events",
        "type-index",
        "click",
        "processed",
        "S",
        "true",
        commit=True,
        dynamodb=c,
    )
    assert result == [{"user_id": "u1", "created_at": "2024-01-01", "status": "updated"}]
    c.update_item.assert_called_once_with(
        TableName="events",
        Key={"user_id": {"S": "u1"}, "created_at": {"S": "2024-01-01"}},
        UpdateExpression="SET #_upd = :_updv",
        ExpressionAttributeNames={"#_upd": "processed"},
        ExpressionAttributeValues={":_updv": {"S": "true"}},
    )


def test_update_by_gsi_partial_error(gsi: ThaGsi) -> None:
    mock = MagicMock()
    mock.describe_table.return_value = {"Table": _UPD_TABLE_DESC}
    mock.query.return_value = {
        "Items": [
            {"order_id": {"S": "o1"}, "status": {"S": "PENDING"}},
            {"order_id": {"S": "o2"}, "status": {"S": "PENDING"}},
        ]
    }
    mock.update_item.side_effect = [RuntimeError("throttled"), None]

    result = gsi.update_by_gsi(
        "orders",
        "status-index",
        "PENDING",
        "status",
        "S",
        "SHIPPED",
        commit=True,
        dynamodb=mock,
    )
    statuses = {r["order_id"]: r["status"] for r in result}
    assert statuses["o1"] == "error"
    assert statuses["o2"] == "updated"
    assert result[0]["message"] == "throttled"


def test_update_by_gsi_bad_index_raises(gsi: ThaGsi) -> None:
    c = _upd_client(_UPD_TABLE_DESC, [])
    with pytest.raises(ValueError, match="GSI 'bad-index' not found"):
        gsi.update_by_gsi("orders", "bad-index", "PENDING", "status", "S", "SHIPPED", dynamodb=c)


# --- batch_update_by_gsi ---

from tha_aws_runner.gsi import BatchUpdateResult  # noqa: E402


def _batch_upd_client(table_desc: dict, items_by_value: dict[str, list[dict]]) -> MagicMock:
    mock = MagicMock()
    mock.describe_table.return_value = {"Table": table_desc}

    def _query(**kwargs: object) -> dict:
        pk_val = next(iter(kwargs["ExpressionAttributeValues"][":_pkv"].values()))  # type: ignore[index]
        return {"Items": items_by_value.get(str(pk_val), [])}

    mock.query.side_effect = _query
    mock.update_item.return_value = {}
    return mock


def test_batch_update_by_gsi_dry_run(gsi: ThaGsi) -> None:
    c = _batch_upd_client(
        _UPD_TABLE_DESC,
        {
            "PENDING": [{"order_id": {"S": "o1"}, "status": {"S": "PENDING"}}],
            "REVIEW": [{"order_id": {"S": "o2"}, "status": {"S": "REVIEW"}}],
        },
    )
    result = gsi.batch_update_by_gsi(
        "orders",
        "status-index",
        ["PENDING", "REVIEW"],
        update_attr="status",
        update_type="S",
        update_value="PROCESSING",
        dynamodb=c,
    )
    assert isinstance(result, BatchUpdateResult)
    assert result.errors == {}
    assert result.results["PENDING"] == [{"order_id": "o1", "status": "dry_run"}]
    assert result.results["REVIEW"] == [{"order_id": "o2", "status": "dry_run"}]
    c.update_item.assert_not_called()


def test_batch_update_by_gsi_commit(gsi: ThaGsi) -> None:
    c = _batch_upd_client(
        _UPD_TABLE_DESC,
        {
            "PENDING": [{"order_id": {"S": "o1"}, "status": {"S": "PENDING"}}],
            "REVIEW": [{"order_id": {"S": "o2"}, "status": {"S": "REVIEW"}}],
        },
    )
    result = gsi.batch_update_by_gsi(
        "orders",
        "status-index",
        ["PENDING", "REVIEW"],
        update_attr="status",
        update_type="S",
        update_value="PROCESSING",
        commit=True,
        dynamodb=c,
    )
    assert result.errors == {}
    assert result.results["PENDING"] == [{"order_id": "o1", "status": "updated"}]
    assert result.results["REVIEW"] == [{"order_id": "o2", "status": "updated"}]
    assert c.update_item.call_count == 2


def test_batch_update_by_gsi_empty_values(gsi: ThaGsi) -> None:
    c = _batch_upd_client(_UPD_TABLE_DESC, {})
    result = gsi.batch_update_by_gsi(
        "orders",
        "status-index",
        [],
        update_attr="status",
        update_type="S",
        update_value="DONE",
        commit=True,
        dynamodb=c,
    )
    assert result.results == {}
    assert result.errors == {}
    c.update_item.assert_not_called()


def test_batch_update_by_gsi_sets_rows(gsi: ThaGsi) -> None:
    c = _batch_upd_client(
        _UPD_TABLE_DESC,
        {"PENDING": [{"order_id": {"S": "o1"}, "status": {"S": "PENDING"}}]},
    )
    result = gsi.batch_update_by_gsi(
        "orders",
        "status-index",
        ["PENDING"],
        update_attr="status",
        update_type="S",
        update_value="DONE",
        dynamodb=c,
    )
    assert gsi.rows is result


def test_batch_update_by_gsi_query_error_captured(gsi: ThaGsi) -> None:
    mock = MagicMock()
    mock.describe_table.return_value = {"Table": _UPD_TABLE_DESC}

    def _query(**kwargs: object) -> dict:
        pk_val = next(iter(kwargs["ExpressionAttributeValues"][":_pkv"].values()))  # type: ignore[index]
        if str(pk_val) == "BAD":
            raise RuntimeError("GSI query failed")
        return {"Items": [{"order_id": {"S": "o1"}, "status": {"S": str(pk_val)}}]}

    mock.query.side_effect = _query
    mock.update_item.return_value = {}

    result = gsi.batch_update_by_gsi(
        "orders",
        "status-index",
        ["PENDING", "BAD"],
        update_attr="status",
        update_type="S",
        update_value="DONE",
        commit=True,
        dynamodb=mock,
    )
    assert "PENDING" in result.results
    assert "BAD" in result.errors
    assert isinstance(result.errors["BAD"], RuntimeError)


def test_batch_update_by_gsi_per_item_error(gsi: ThaGsi) -> None:
    mock = MagicMock()
    mock.describe_table.return_value = {"Table": _UPD_TABLE_DESC}
    mock.query.return_value = {
        "Items": [
            {"order_id": {"S": "o1"}, "status": {"S": "PENDING"}},
            {"order_id": {"S": "o2"}, "status": {"S": "PENDING"}},
        ]
    }
    mock.update_item.side_effect = [RuntimeError("throttled"), None]

    result = gsi.batch_update_by_gsi(
        "orders",
        "status-index",
        ["PENDING"],
        update_attr="status",
        update_type="S",
        update_value="DONE",
        commit=True,
        dynamodb=mock,
    )
    assert result.errors == {}
    item_statuses = {r["order_id"]: r["status"] for r in result.results["PENDING"]}
    assert item_statuses["o1"] == "error"
    assert item_statuses["o2"] == "updated"


def test_batch_update_by_gsi_with_rows(gsi: ThaGsi) -> None:
    c = _batch_upd_client(
        _UPD_TABLE_DESC,
        {"PENDING": [{"order_id": {"S": "o1"}, "status": {"S": "PENDING"}}]},
    )
    rows = [{"status": "PENDING", "region": "us"}]
    result = gsi.batch_update_by_gsi(
        "orders",
        "status-index",
        rows=rows,
        gsi_col="status",
        update_attr="status",
        update_type="S",
        update_value="DONE",
        dynamodb=c,
    )
    assert "PENDING" in result.results
    assert result.errors == {}


def test_batch_update_by_gsi_show_progress(gsi: ThaGsi) -> None:
    c = _batch_upd_client(
        _UPD_TABLE_DESC,
        {"PENDING": [{"order_id": {"S": "o1"}, "status": {"S": "PENDING"}}]},
    )
    result = gsi.batch_update_by_gsi(
        "orders",
        "status-index",
        ["PENDING"],
        update_attr="status",
        update_type="S",
        update_value="DONE",
        dynamodb=c,
        show_progress=True,
        progress_desc="updating",
    )
    assert "PENDING" in result.results
    assert result.errors == {}


def test_batch_update_by_gsi_table_desc_cached(gsi: ThaGsi) -> None:
    c = _batch_upd_client(
        _UPD_TABLE_DESC,
        {
            "PENDING": [{"order_id": {"S": "o1"}, "status": {"S": "PENDING"}}],
            "REVIEW": [{"order_id": {"S": "o2"}, "status": {"S": "REVIEW"}}],
        },
    )
    gsi.batch_update_by_gsi(
        "orders",
        "status-index",
        ["PENDING", "REVIEW"],
        update_attr="status",
        update_type="S",
        update_value="DONE",
        dynamodb=c,
    )
    assert c.describe_table.call_count == 1


def test_batch_update_by_gsi_bad_index_raises(gsi: ThaGsi) -> None:
    c = _batch_upd_client(_UPD_TABLE_DESC, {})
    with pytest.raises(ValueError, match="GSI 'bad-index' not found"):
        gsi.batch_update_by_gsi(
            "orders",
            "bad-index",
            ["PENDING"],
            update_attr="status",
            update_type="S",
            update_value="DONE",
            dynamodb=c,
        )


def test_update_by_gsi_increment(gsi: ThaGsi) -> None:
    c = _upd_client(
        _UPD_TABLE_DESC,
        [{"order_id": {"S": "o1"}, "status": {"S": "PENDING"}}],
    )
    result = gsi.update_by_gsi(
        "orders",
        "status-index",
        "PENDING",
        "status",
        "N",
        1,
        increment=True,
        incr_col="retry_count",
        commit=True,
        dynamodb=c,
    )
    assert result == [{"order_id": "o1", "status": "updated"}]
    c.update_item.assert_called_once_with(
        TableName="orders",
        Key={"order_id": {"S": "o1"}},
        UpdateExpression="ADD #_upd :_updv",
        ExpressionAttributeNames={"#_upd": "retry_count"},
        ExpressionAttributeValues={":_updv": {"N": "1"}},
    )


def test_update_by_gsi_increment_missing_incr_col_raises(gsi: ThaGsi) -> None:
    c = _upd_client(_UPD_TABLE_DESC, [])
    with pytest.raises(ValueError, match="incr_col is required when increment=True"):
        gsi.update_by_gsi(
            "orders",
            "status-index",
            "PENDING",
            "status",
            "N",
            1,
            increment=True,
            dynamodb=c,
        )


def test_update_by_gsi_incr_col(gsi: ThaGsi) -> None:
    c = _upd_client(
        _UPD_TABLE_DESC,
        [{"order_id": {"S": "o1"}, "status": {"S": "PENDING"}}],
    )
    result = gsi.update_by_gsi(
        "orders",
        "status-index",
        "PENDING",
        "status",
        "N",
        1,
        increment=True,
        incr_col="view_count",
        commit=True,
        dynamodb=c,
    )
    assert result == [{"order_id": "o1", "status": "updated"}]
    c.update_item.assert_called_once_with(
        TableName="orders",
        Key={"order_id": {"S": "o1"}},
        UpdateExpression="ADD #_upd :_updv",
        ExpressionAttributeNames={"#_upd": "view_count"},
        ExpressionAttributeValues={":_updv": {"N": "1"}},
    )


def test_update_by_gsi_incr_col_without_increment_raises(gsi: ThaGsi) -> None:
    c = _upd_client(_UPD_TABLE_DESC, [])
    with pytest.raises(ValueError, match="incr_col requires increment=True"):
        gsi.update_by_gsi(
            "orders",
            "status-index",
            "PENDING",
            "status",
            "S",
            "SHIPPED",
            incr_col="view_count",
            dynamodb=c,
        )


def test_batch_update_by_gsi_increment(gsi: ThaGsi) -> None:
    c = _batch_upd_client(
        _UPD_TABLE_DESC,
        {"PENDING": [{"order_id": {"S": "o1"}, "status": {"S": "PENDING"}}]},
    )
    result = gsi.batch_update_by_gsi(
        "orders",
        "status-index",
        ["PENDING"],
        update_attr="status",
        update_type="N",
        update_value=1,
        increment=True,
        incr_col="retry_count",
        commit=True,
        dynamodb=c,
    )
    assert result.errors == {}
    assert result.results["PENDING"] == [{"order_id": "o1", "status": "updated"}]
    c.update_item.assert_called_once_with(
        TableName="orders",
        Key={"order_id": {"S": "o1"}},
        UpdateExpression="ADD #_upd :_updv",
        ExpressionAttributeNames={"#_upd": "retry_count"},
        ExpressionAttributeValues={":_updv": {"N": "1"}},
    )


def test_batch_update_by_gsi_increment_missing_incr_col_raises(gsi: ThaGsi) -> None:
    c = _batch_upd_client(_UPD_TABLE_DESC, {})
    with pytest.raises(ValueError, match="incr_col is required when increment=True"):
        gsi.batch_update_by_gsi(
            "orders",
            "status-index",
            ["PENDING"],
            update_attr="status",
            update_type="N",
            update_value=1,
            increment=True,
            dynamodb=c,
        )


def test_batch_update_by_gsi_incr_col(gsi: ThaGsi) -> None:
    c = _batch_upd_client(
        _UPD_TABLE_DESC,
        {"PENDING": [{"order_id": {"S": "o1"}, "status": {"S": "PENDING"}}]},
    )
    result = gsi.batch_update_by_gsi(
        "orders",
        "status-index",
        ["PENDING"],
        update_attr="status",
        update_type="N",
        update_value=1,
        increment=True,
        incr_col="view_count",
        commit=True,
        dynamodb=c,
    )
    assert result.errors == {}
    assert result.results["PENDING"] == [{"order_id": "o1", "status": "updated"}]
    c.update_item.assert_called_once_with(
        TableName="orders",
        Key={"order_id": {"S": "o1"}},
        UpdateExpression="ADD #_upd :_updv",
        ExpressionAttributeNames={"#_upd": "view_count"},
        ExpressionAttributeValues={":_updv": {"N": "1"}},
    )


def test_batch_update_by_gsi_incr_col_without_increment_raises(gsi: ThaGsi) -> None:
    c = _batch_upd_client(_UPD_TABLE_DESC, {})
    with pytest.raises(ValueError, match="incr_col requires increment=True"):
        gsi.batch_update_by_gsi(
            "orders",
            "status-index",
            ["PENDING"],
            update_attr="status",
            update_type="S",
            update_value="DONE",
            incr_col="view_count",
            dynamodb=c,
        )


# --- skip_statuses ---


def test_batch_query_skip_statuses_default(gsi: ThaGsi) -> None:
    c = _client_fn(_TABLE_DESC)
    rows = [
        {"email": "a@x.com", "row status": ""},
        {"email": "b@x.com", "row status": "error"},
        {"email": "c@x.com", "row status": "warning"},
    ]
    result = gsi.batch_query("users", "email-index", rows=rows, gsi_col="email", dynamodb=c)
    assert set(result.results) == {"a@x.com"}
    assert result.errors == {}


def test_batch_query_skip_statuses_empty_disables(gsi: ThaGsi) -> None:
    c = _client_fn(_TABLE_DESC)
    rows = [
        {"email": "a@x.com", "row status": "error"},
        {"email": "b@x.com", "row status": "warning"},
    ]
    result = gsi.batch_query(
        "users",
        "email-index",
        rows=rows,
        gsi_col="email",
        skip_statuses=[],
        dynamodb=c,
    )
    assert set(result.results) == {"a@x.com", "b@x.com"}


def test_batch_query_skip_statuses_custom_col(gsi: ThaGsi) -> None:
    c = _client_fn(_TABLE_DESC)
    rows = [
        {"email": "a@x.com", "state": "error"},
        {"email": "b@x.com", "state": "ok"},
    ]
    result = gsi.batch_query(
        "users",
        "email-index",
        rows=rows,
        gsi_col="email",
        status_col="state",
        dynamodb=c,
    )
    assert set(result.results) == {"b@x.com"}


def test_batch_count_skip_statuses_default(gsi: ThaGsi) -> None:
    c = _count_client_fn(_TABLE_DESC)
    rows = [
        {"email": "ab", "row status": ""},
        {"email": "abc", "row status": "error"},
    ]
    result = gsi.batch_count("users", "email-index", rows=rows, gsi_col="email", dynamodb=c)
    assert set(result.results) == {"ab"}
    assert result.errors == {}


def test_batch_count_skip_statuses_empty_disables(gsi: ThaGsi) -> None:
    c = _count_client_fn(_TABLE_DESC)
    rows = [
        {"email": "ab", "row status": "error"},
        {"email": "abc", "row status": "warning"},
    ]
    result = gsi.batch_count(
        "users",
        "email-index",
        rows=rows,
        gsi_col="email",
        skip_statuses=[],
        dynamodb=c,
    )
    assert set(result.results) == {"ab", "abc"}


def test_batch_update_by_gsi_skip_statuses_default(gsi: ThaGsi) -> None:
    c = _batch_upd_client(
        _UPD_TABLE_DESC,
        {"PENDING": [{"order_id": {"S": "o1"}, "status": {"S": "PENDING"}}]},
    )
    rows = [
        {"status": "PENDING", "row status": ""},
        {"status": "REVIEW", "row status": "error"},
        {"status": "HOLD", "row status": "warning"},
    ]
    result = gsi.batch_update_by_gsi(
        "orders",
        "status-index",
        rows=rows,
        gsi_col="status",
        update_attr="status",
        update_type="S",
        update_value="DONE",
        dynamodb=c,
    )
    assert set(result.results) == {"PENDING"}
    assert result.errors == {}


def test_batch_update_by_gsi_skip_statuses_empty_disables(gsi: ThaGsi) -> None:
    c = _batch_upd_client(
        _UPD_TABLE_DESC,
        {
            "PENDING": [{"order_id": {"S": "o1"}, "status": {"S": "PENDING"}}],
            "REVIEW": [{"order_id": {"S": "o2"}, "status": {"S": "REVIEW"}}],
        },
    )
    rows = [
        {"status": "PENDING", "row status": "error"},
        {"status": "REVIEW", "row status": "warning"},
    ]
    result = gsi.batch_update_by_gsi(
        "orders",
        "status-index",
        rows=rows,
        gsi_col="status",
        update_attr="status",
        update_type="S",
        update_value="DONE",
        skip_statuses=[],
        dynamodb=c,
    )
    assert set(result.results) == {"PENDING", "REVIEW"}
