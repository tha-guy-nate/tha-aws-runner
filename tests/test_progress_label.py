"""progress_desc is the step prefix; label overrides the default text after it."""

from collections.abc import Callable
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from tha_aws_runner.aws_base import AWSBase, _compose_label
from tha_aws_runner.dynamodb import ThaDdb
from tha_aws_runner.gsi import ThaGsi
from tha_aws_runner.s3 import ThaS3

_GSI_DESC = {
    "TableName": "users",
    "KeySchema": [{"AttributeName": "email", "KeyType": "HASH"}],
    "AttributeDefinitions": [{"AttributeName": "email", "AttributeType": "S"}],
    "GlobalSecondaryIndexes": [
        {"IndexName": "email-index", "KeySchema": [{"AttributeName": "email", "KeyType": "HASH"}]}
    ],
}


def _gsi_client() -> MagicMock:
    c = MagicMock()
    c.describe_table.return_value = {"Table": _GSI_DESC}
    c.query.return_value = {"Items": [], "Count": 0}
    return c


def _ddb(client: MagicMock) -> ThaDdb:
    ddb = ThaDdb(region="us-east-1")
    ddb._thread_local.dynamodb = client
    return ddb


def _s3(client: MagicMock) -> ThaS3:
    s3 = ThaS3(region="us-east-1")
    s3._thread_local.s3 = client
    return s3


def _ddb_client() -> MagicMock:
    c = MagicMock()
    c.batch_get_item.return_value = {"Responses": {"t": []}, "UnprocessedKeys": {}}
    c.batch_write_item.return_value = {"UnprocessedItems": {}}
    return c


def _s3_client() -> MagicMock:
    c = MagicMock()
    c.get_paginator.return_value.paginate.return_value = [{"Contents": [{"Key": "a.csv"}]}]
    c.get_object.return_value = {"Body": BytesIO(b"x")}
    return c


# name -> (default text, call(extra_kwargs))
_CASES: dict[str, tuple[str, Callable[[dict[str, Any]], None]]] = {
    "batch_fetch_by_pk": (
        "Fetching by pk",
        lambda kw: _ddb(_ddb_client()).batch_fetch_by_pk(
            [{"id": "1"}], "id", table_name="t", key_name="id", key_type="S", **kw
        ),
    ),
    "batch_update_by_pk": (
        "Updating by pk (dry run)",
        lambda kw: _ddb(_ddb_client()).batch_update_by_pk(
            [{"id": "1", "v": "x"}], "id", "id", "S", "a", "S", "v", table_name="t", **kw
        ),
    ),
    "batch_delete_by_pk": (
        "Deleting by pk (dry run)",
        lambda kw: _ddb(_ddb_client()).batch_delete_by_pk(
            [{"id": "1"}], "id", "id", "S", table_name="t", **kw
        ),
    ),
    "batch_write": (
        "Writing items",
        lambda kw: _ddb(_ddb_client()).batch_write("t", [{"id": {"S": "1"}}], commit=True, **kw),
    ),
    "batch_query": (
        "Querying GSI",
        lambda kw: ThaGsi().batch_query(
            "users", "email-index", ["a"], dynamodb=_gsi_client(), **kw
        ),
    ),
    "batch_count": (
        "Counting GSI",
        lambda kw: ThaGsi().batch_count(
            "users", "email-index", ["a"], dynamodb=_gsi_client(), **kw
        ),
    ),
    "batch_update_by_gsi": (
        "Updating by GSI (dry run)",
        lambda kw: ThaGsi().batch_update_by_gsi(
            "users",
            "email-index",
            ["a"],
            update_attr="x",
            update_type="S",
            update_value="y",
            dynamodb=_gsi_client(),
            **kw,
        ),
    ),
    "batch_download": (
        "Downloading files",
        lambda kw: _s3(_s3_client()).batch_download(
            [{"key": "a.csv"}], key_col="key", bucket="b", **kw
        ),
    ),
    "download_prefix": (
        "Downloading files",
        lambda kw: _s3(_s3_client()).download_prefix("b", "", **kw),
    ),
}


def _desc_for(name: str, **kw: Any) -> str:
    _, call = _CASES[name]
    with patch.object(
        AWSBase, "_progress_iter", autospec=True, side_effect=lambda self, it, **k: it
    ) as spy:
        call({"show_progress": True, **kw})
    return spy.call_args.kwargs["desc"]  # type: ignore[no-any-return]


@pytest.mark.parametrize("name", list(_CASES))
def test_default_text_without_prefix_or_label(name: str) -> None:
    assert _desc_for(name) == _CASES[name][0]


@pytest.mark.parametrize("name", list(_CASES))
def test_progress_desc_is_prefix_before_default_text(name: str) -> None:
    assert _desc_for(name, progress_desc="[4/7]") == f"[4/7]: {_CASES[name][0]}"


@pytest.mark.parametrize("name", list(_CASES))
def test_label_overrides_default_text(name: str) -> None:
    suffix = " (dry run)" if _CASES[name][0].endswith(" (dry run)") else ""
    assert _desc_for(name, label="Sending mock payloads") == f"Sending mock payloads{suffix}"


@pytest.mark.parametrize("name", list(_CASES))
def test_prefix_and_label_combine(name: str) -> None:
    suffix = " (dry run)" if _CASES[name][0].endswith(" (dry run)") else ""
    assert (
        _desc_for(name, progress_desc="[4/7]", label="Sending mock payloads")
        == f"[4/7]: Sending mock payloads{suffix}"
    )


def test_compose_label_variants() -> None:
    assert _compose_label(None, None, "x") == "x"
    assert _compose_label("", None, "x") == "x"
    assert _compose_label("[1/2]", None, "x") == "[1/2]: x"
    assert _compose_label(None, "y", "x") == "y"
    assert _compose_label("[1/2]", "y", "x") == "[1/2]: y"
    assert _compose_label(None, "", "x") == ""
