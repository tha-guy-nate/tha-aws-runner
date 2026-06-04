from io import BytesIO
from unittest.mock import MagicMock

import pytest

from tha_aws_runner.s3 import ThaS3, _parse_s3_uri


def make_s3(mock_client: MagicMock) -> ThaS3:
    s3 = ThaS3(region="us-east-1")
    s3._thread_local.s3 = mock_client
    return s3


# --- _parse_s3_uri ---


def test_parse_s3_uri_happy():
    assert _parse_s3_uri("s3://my-bucket/path/to/key.csv") == ("my-bucket", "path/to/key.csv")


def test_parse_s3_uri_simple_key():
    assert _parse_s3_uri("s3://my-bucket/file.txt") == ("my-bucket", "file.txt")


def test_parse_s3_uri_no_prefix_raises():
    with pytest.raises(ValueError, match="Invalid S3 URI"):
        _parse_s3_uri("my-bucket/key")


def test_parse_s3_uri_no_key_raises():
    with pytest.raises(ValueError, match="Missing key"):
        _parse_s3_uri("s3://my-bucket")


def test_parse_s3_uri_empty_key_raises():
    with pytest.raises(ValueError, match="Key is empty"):
        _parse_s3_uri("s3://my-bucket/")


def test_parse_s3_uri_empty_bucket_raises():
    with pytest.raises(ValueError, match="Bucket name is empty"):
        _parse_s3_uri("s3:///key")


# --- upload_file ---


def test_upload_file_dry_run(mock_s3_client):
    s3 = make_s3(mock_s3_client)
    result = s3.upload_file("my-bucket", "data.csv", data=b"hello")
    assert result == {"bucket": "my-bucket", "key": "data.csv", "status": "dry_run", "bytes": 5}
    mock_s3_client.put_object.assert_not_called()
    assert s3.rows is result


def test_upload_file_from_str(mock_s3_client):
    mock_s3_client.put_object.return_value = {}
    s3 = make_s3(mock_s3_client)
    result = s3.upload_file("my-bucket", "data.csv", data="col1,col2\n1,2", commit=True)
    assert result["bytes"] == len(b"col1,col2\n1,2")
    mock_s3_client.put_object.assert_called_once_with(
        Bucket="my-bucket", Key="data.csv", Body=b"col1,col2\n1,2"
    )


def test_upload_file_from_str_custom_encoding(mock_s3_client):
    mock_s3_client.put_object.return_value = {}
    s3 = make_s3(mock_s3_client)
    result = s3.upload_file("b", "k", data="héllo", encoding="latin-1", commit=True)
    assert result["bytes"] == len("héllo".encode("latin-1"))


def test_upload_file_from_bytes(mock_s3_client):
    mock_s3_client.put_object.return_value = {}
    s3 = make_s3(mock_s3_client)
    result = s3.upload_file("my-bucket", "path/to/key.csv", data=b"hello,world", commit=True)
    assert result == {
        "bucket": "my-bucket", "key": "path/to/key.csv", "status": "uploaded", "bytes": 11
    }
    assert s3.rows is result
    mock_s3_client.put_object.assert_called_once_with(
        Bucket="my-bucket", Key="path/to/key.csv", Body=b"hello,world"
    )


def test_upload_file_from_path(mock_s3_client, tmp_path):
    local = tmp_path / "test.txt"
    local.write_bytes(b"file content")
    mock_s3_client.put_object.return_value = {}
    s3 = make_s3(mock_s3_client)
    result = s3.upload_file("my-bucket", "test.txt", local_path=str(local), commit=True)
    assert result["status"] == "uploaded"
    assert result["bytes"] == 12


def test_upload_file_via_uri(mock_s3_client):
    mock_s3_client.put_object.return_value = {}
    s3 = make_s3(mock_s3_client)
    result = s3.upload_file(uri="s3://my-bucket/path/to/key.csv", data=b"hello", commit=True)
    assert result["bucket"] == "my-bucket"
    assert result["key"] == "path/to/key.csv"
    assert result["status"] == "uploaded"


def test_upload_file_no_bucket_or_uri_raises(mock_s3_client):
    s3 = make_s3(mock_s3_client)
    with pytest.raises(ValueError, match="Provide uri or both bucket and key"):
        s3.upload_file(data=b"x")


def test_upload_file_no_source_raises(mock_s3_client):
    s3 = make_s3(mock_s3_client)
    with pytest.raises(ValueError, match="Either local_path or data must be provided"):
        s3.upload_file("my-bucket", "key")


def test_upload_file_both_sources_raises(mock_s3_client):
    s3 = make_s3(mock_s3_client)
    with pytest.raises(ValueError, match="not both"):
        s3.upload_file("my-bucket", "key", local_path="/some/path", data=b"bytes")


def test_upload_file_uses_injected_client():
    injected = MagicMock()
    injected.put_object.return_value = {}
    other = MagicMock()
    s3 = ThaS3()
    s3._s3 = other
    result = s3.upload_file("b", "k", data=b"x", commit=True, s3=injected)
    assert result["status"] == "uploaded"
    other.put_object.assert_not_called()


# --- list_files ---


def test_list_files_returns_keys(mock_s3_client):
    mock_s3_client.get_paginator.return_value.paginate.return_value = [
        {"Contents": [{"Key": "data/a.csv"}, {"Key": "data/b.csv"}]},
    ]
    s3 = make_s3(mock_s3_client)
    result = s3.list_files("my-bucket", "data/")
    assert result == ["data/a.csv", "data/b.csv"]
    assert s3.rows is result


def test_list_files_empty_prefix(mock_s3_client):
    mock_s3_client.get_paginator.return_value.paginate.return_value = [
        {"Contents": [{"Key": "file.csv"}]},
    ]
    s3 = make_s3(mock_s3_client)
    result = s3.list_files("my-bucket")
    assert result == ["file.csv"]


def test_list_files_no_contents(mock_s3_client):
    mock_s3_client.get_paginator.return_value.paginate.return_value = [{}]
    s3 = make_s3(mock_s3_client)
    result = s3.list_files("my-bucket", "empty/")
    assert result == []


# --- delete_file ---


def test_delete_file_dry_run(mock_s3_client):
    s3 = make_s3(mock_s3_client)
    result = s3.delete_file("my-bucket", "data.csv")
    assert result == {"bucket": "my-bucket", "key": "data.csv", "status": "dry_run"}
    mock_s3_client.delete_object.assert_not_called()
    assert s3.rows is result


def test_delete_file_commit(mock_s3_client):
    mock_s3_client.delete_object.return_value = {}
    s3 = make_s3(mock_s3_client)
    result = s3.delete_file("my-bucket", "data.csv", commit=True)
    assert result == {"bucket": "my-bucket", "key": "data.csv", "status": "deleted"}
    mock_s3_client.delete_object.assert_called_once_with(Bucket="my-bucket", Key="data.csv")
    assert s3.rows is result


def test_delete_file_via_uri(mock_s3_client):
    mock_s3_client.delete_object.return_value = {}
    s3 = make_s3(mock_s3_client)
    result = s3.delete_file(uri="s3://my-bucket/data.csv", commit=True)
    assert result["bucket"] == "my-bucket"
    assert result["key"] == "data.csv"
    assert result["status"] == "deleted"


def test_delete_file_no_bucket_or_uri_raises(mock_s3_client):
    s3 = make_s3(mock_s3_client)
    with pytest.raises(ValueError, match="Provide uri or both bucket and key"):
        s3.delete_file()


# --- download_file ---


def test_download_file_to_memory(mock_s3_client):
    mock_s3_client.get_object.return_value = {"Body": BytesIO(b"csv,data")}
    s3 = make_s3(mock_s3_client)
    result = s3.download_file("my-bucket", "data.csv")
    assert result["status"] == "downloaded"
    assert result["bytes"] == 8
    assert result["data"] == b"csv,data"
    assert s3.rows is result


def test_download_file_to_path(mock_s3_client, tmp_path):
    mock_s3_client.get_object.return_value = {"Body": BytesIO(b"file content")}
    s3 = make_s3(mock_s3_client)
    dest = tmp_path / "output.txt"
    result = s3.download_file("my-bucket", "output.txt", local_path=str(dest))
    assert result["status"] == "downloaded"
    assert result["bytes"] == 12
    assert "data" not in result
    assert dest.read_bytes() == b"file content"


def test_download_file_via_uri(mock_s3_client):
    mock_s3_client.get_object.return_value = {"Body": BytesIO(b"data")}
    s3 = make_s3(mock_s3_client)
    result = s3.download_file(uri="s3://my-bucket/data.csv")
    assert result["bucket"] == "my-bucket"
    assert result["key"] == "data.csv"
    assert result["status"] == "downloaded"


def test_download_file_no_bucket_or_uri_raises(mock_s3_client):
    s3 = make_s3(mock_s3_client)
    with pytest.raises(ValueError, match="Provide uri or both bucket and key"):
        s3.download_file()


def test_download_file_decoded_to_str(mock_s3_client):
    mock_s3_client.get_object.return_value = {"Body": BytesIO(b"col1,col2\n1,2")}
    s3 = make_s3(mock_s3_client)
    result = s3.download_file("my-bucket", "data.csv", encoding="utf-8")
    assert isinstance(result["data"], str)
    assert result["data"] == "col1,col2\n1,2"


def test_download_file_no_encoding_returns_bytes(mock_s3_client):
    mock_s3_client.get_object.return_value = {"Body": BytesIO(b"raw")}
    s3 = make_s3(mock_s3_client)
    result = s3.download_file("my-bucket", "f.bin")
    assert isinstance(result["data"], bytes)


def test_download_file_uses_injected_client():
    injected = MagicMock()
    injected.get_object.return_value = {"Body": BytesIO(b"x")}
    other = MagicMock()
    s3 = ThaS3()
    s3._s3 = other
    result = s3.download_file("b", "k", s3=injected)
    assert result["status"] == "downloaded"
    other.get_object.assert_not_called()


# --- download_prefix ---


def test_download_prefix_lists_then_downloads(mock_s3_client):
    mock_s3_client.get_paginator.return_value.paginate.return_value = [
        {"Contents": [{"Key": "data/a.csv"}, {"Key": "data/b.csv"}]}
    ]
    mock_s3_client.get_object.return_value = {"Body": BytesIO(b"content")}
    s3 = make_s3(mock_s3_client)
    result = s3.download_prefix("my-bucket", "data/")
    assert len(result) == 2
    assert all(r["status"] == "downloaded" for r in result)
    assert result[0]["key"] == "data/a.csv"
    assert result[1]["key"] == "data/b.csv"


def test_download_prefix_empty_prefix(mock_s3_client):
    mock_s3_client.get_paginator.return_value.paginate.return_value = [
        {"Contents": [{"Key": "file.csv"}]}
    ]
    mock_s3_client.get_object.return_value = {"Body": BytesIO(b"x")}
    s3 = make_s3(mock_s3_client)
    result = s3.download_prefix("my-bucket")
    assert len(result) == 1
    assert result[0]["key"] == "file.csv"


def test_download_prefix_to_local_dir(mock_s3_client, tmp_path):
    mock_s3_client.get_paginator.return_value.paginate.return_value = [
        {"Contents": [{"Key": "reports/q1.csv"}]}
    ]
    mock_s3_client.get_object.return_value = {"Body": BytesIO(b"data")}
    s3 = make_s3(mock_s3_client)
    result = s3.download_prefix("my-bucket", "reports/", local_dir=str(tmp_path))
    assert result[0]["status"] == "downloaded"
    assert (tmp_path / "reports" / "q1.csv").read_bytes() == b"data"


def test_download_prefix_empty_prefix_returns_empty(mock_s3_client):
    mock_s3_client.get_paginator.return_value.paginate.return_value = [{}]
    s3 = make_s3(mock_s3_client)
    result = s3.download_prefix("my-bucket", "empty/")
    assert result == []


# --- batch_download ---


def test_batch_download_key_col_fixed_bucket(mock_s3_client):
    mock_s3_client.get_object.return_value = {"Body": BytesIO(b"data")}
    s3 = make_s3(mock_s3_client)
    rows = [{"key": "a.csv"}, {"key": "b.csv"}]
    result = s3.batch_download(rows, key_col="key", bucket="my-bucket")
    assert len(result) == 2
    assert all(r["status"] == "downloaded" for r in result)
    assert result[0]["key"] == "a.csv"
    assert result[1]["key"] == "b.csv"
    assert s3.rows is result


def test_batch_download_uri_col(mock_s3_client):
    mock_s3_client.get_object.return_value = {"Body": BytesIO(b"data")}
    s3 = make_s3(mock_s3_client)
    rows = [{"uri": "s3://my-bucket/a.csv"}, {"uri": "s3://my-bucket/b.csv"}]
    result = s3.batch_download(rows, uri_col="uri")
    assert len(result) == 2
    assert result[0]["bucket"] == "my-bucket"
    assert result[1]["key"] == "b.csv"


def test_batch_download_bucket_col(mock_s3_client):
    mock_s3_client.get_object.return_value = {"Body": BytesIO(b"data")}
    s3 = make_s3(mock_s3_client)
    rows = [
        {"key": "a.csv", "bkt": "bucket-1"},
        {"key": "b.csv", "bkt": "bucket-2"},
    ]
    result = s3.batch_download(rows, key_col="key", bucket_col="bkt")
    assert len(result) == 2
    assert result[0]["bucket"] == "bucket-1"
    assert result[1]["bucket"] == "bucket-2"


def test_batch_download_to_local_dir(mock_s3_client, tmp_path):
    mock_s3_client.get_object.return_value = {"Body": BytesIO(b"hello")}
    s3 = make_s3(mock_s3_client)
    rows = [{"key": "reports/a.csv"}]
    result = s3.batch_download(rows, key_col="key", bucket="my-bucket", local_dir=str(tmp_path))
    assert result[0]["status"] == "downloaded"
    assert (tmp_path / "reports" / "a.csv").read_bytes() == b"hello"


def test_batch_download_error_captured_per_row(mock_s3_client):
    def _side_effect(**kwargs):
        if kwargs["Key"] == "bad.csv":
            raise Exception("S3 error")
        return {"Body": BytesIO(b"ok")}

    mock_s3_client.get_object.side_effect = _side_effect
    s3 = make_s3(mock_s3_client)
    rows = [{"key": "good.csv"}, {"key": "bad.csv"}]
    result = s3.batch_download(rows, key_col="key", bucket="my-bucket")
    assert result[0]["status"] == "downloaded"
    assert result[1]["status"] == "error"
    assert "S3 error" in result[1]["message"]


def test_batch_download_invalid_uri_captured_per_row(mock_s3_client):
    s3 = make_s3(mock_s3_client)
    rows = [{"uri": "not-a-uri"}]
    result = s3.batch_download(rows, uri_col="uri")
    assert result[0]["status"] == "error"
    assert "Invalid S3 URI" in result[0]["message"]


def test_batch_download_threaded(mock_s3_client):
    mock_s3_client.get_object.return_value = {"Body": BytesIO(b"data")}
    s3 = make_s3(mock_s3_client)
    rows = [{"key": f"file{i}.csv"} for i in range(6)]
    result = s3.batch_download(
        rows, key_col="key", bucket="my-bucket", workers=3, s3=mock_s3_client
    )
    assert len(result) == 6
    assert all(r["status"] == "downloaded" for r in result)
    assert mock_s3_client.get_object.call_count == 6


def test_batch_download_requires_uri_or_key_col(mock_s3_client):
    s3 = make_s3(mock_s3_client)
    with pytest.raises(ValueError, match="Provide either uri_col or key_col"):
        s3.batch_download([{"key": "a.csv"}])


def test_batch_download_rejects_both_uri_and_key_col(mock_s3_client):
    s3 = make_s3(mock_s3_client)
    with pytest.raises(ValueError, match="not both"):
        s3.batch_download([{"key": "a.csv"}], uri_col="key", key_col="key")


def test_batch_download_key_col_requires_bucket_or_bucket_col(mock_s3_client):
    s3 = make_s3(mock_s3_client)
    with pytest.raises(ValueError, match="exactly one of bucket or bucket_col"):
        s3.batch_download([{"key": "a.csv"}], key_col="key")


# --- ARN resolution ---

_BUCKET_ARN = "arn:aws:s3:::my-bucket"
_OBJECT_ARN = "arn:aws:s3:::my-bucket/reports/jan.csv"


def test_resolve_bucket_plain():
    assert ThaS3._resolve_bucket("my-bucket") == "my-bucket"


def test_resolve_bucket_arn():
    assert ThaS3._resolve_bucket(_BUCKET_ARN) == "my-bucket"


def test_resolve_bucket_from_object_arn():
    assert ThaS3._resolve_bucket(_OBJECT_ARN) == "my-bucket"


def test_resolve_uri_or_arn_s3_uri():
    assert ThaS3._resolve_uri_or_arn("s3://my-bucket/reports/jan.csv") == (
        "my-bucket", "reports/jan.csv"
    )


def test_resolve_uri_or_arn_object_arn():
    assert ThaS3._resolve_uri_or_arn(_OBJECT_ARN) == ("my-bucket", "reports/jan.csv")


def test_resolve_uri_or_arn_bucket_arn_raises():
    with pytest.raises(ValueError, match="Could not extract bucket/key"):
        ThaS3._resolve_uri_or_arn(_BUCKET_ARN)


def test_upload_file_via_object_arn(mock_s3_client):
    mock_s3_client.put_object.return_value = {}
    s3 = make_s3(mock_s3_client)
    result = s3.upload_file(uri=_OBJECT_ARN, data=b"data", commit=True)
    assert result["bucket"] == "my-bucket"
    assert result["key"] == "reports/jan.csv"
    mock_s3_client.put_object.assert_called_once_with(
        Bucket="my-bucket", Key="reports/jan.csv", Body=b"data"
    )


def test_upload_file_bucket_arn(mock_s3_client):
    mock_s3_client.put_object.return_value = {}
    s3 = make_s3(mock_s3_client)
    result = s3.upload_file(_BUCKET_ARN, "reports/jan.csv", data=b"x", commit=True)
    assert result["bucket"] == "my-bucket"
    mock_s3_client.put_object.assert_called_once_with(
        Bucket="my-bucket", Key="reports/jan.csv", Body=b"x"
    )


def test_download_file_via_object_arn(mock_s3_client):
    mock_s3_client.get_object.return_value = {"Body": BytesIO(b"content")}
    s3 = make_s3(mock_s3_client)
    result = s3.download_file(uri=_OBJECT_ARN)
    assert result["bucket"] == "my-bucket"
    assert result["key"] == "reports/jan.csv"
    mock_s3_client.get_object.assert_called_once_with(Bucket="my-bucket", Key="reports/jan.csv")


def test_delete_file_via_object_arn(mock_s3_client):
    mock_s3_client.delete_object.return_value = {}
    s3 = make_s3(mock_s3_client)
    result = s3.delete_file(uri=_OBJECT_ARN, commit=True)
    assert result["bucket"] == "my-bucket"
    assert result["key"] == "reports/jan.csv"
    assert result["status"] == "deleted"


def test_list_files_bucket_arn(mock_s3_client):
    mock_s3_client.get_paginator.return_value.paginate.return_value = [
        {"Contents": [{"Key": "a.csv"}]}
    ]
    s3 = make_s3(mock_s3_client)
    result = s3.list_files(_BUCKET_ARN)
    assert result == ["a.csv"]
    mock_s3_client.get_paginator.return_value.paginate.assert_called_once_with(
        Bucket="my-bucket", Prefix=""
    )


def test_batch_download_bucket_arn(mock_s3_client):
    mock_s3_client.get_object.return_value = {"Body": BytesIO(b"data")}
    s3 = make_s3(mock_s3_client)
    rows = [{"key": "a.csv"}]
    result = s3.batch_download(rows, key_col="key", bucket=_BUCKET_ARN)
    assert result[0]["bucket"] == "my-bucket"
    assert result[0]["status"] == "downloaded"


# --- object_exists ---


def test_object_exists_true(mock_s3_client):
    mock_s3_client.head_object.return_value = {}
    s3 = make_s3(mock_s3_client)
    assert s3.object_exists("my-bucket", "data.csv") is True
    mock_s3_client.head_object.assert_called_once_with(Bucket="my-bucket", Key="data.csv")


def test_object_exists_false(mock_s3_client):
    from botocore.exceptions import ClientError
    err = ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
    mock_s3_client.head_object.side_effect = err
    s3 = make_s3(mock_s3_client)
    assert s3.object_exists("my-bucket", "missing.csv") is False


def test_object_exists_other_error_raises(mock_s3_client):
    from botocore.exceptions import ClientError
    err = ClientError({"Error": {"Code": "403", "Message": "Forbidden"}}, "HeadObject")
    mock_s3_client.head_object.side_effect = err
    s3 = make_s3(mock_s3_client)
    with pytest.raises(ClientError):
        s3.object_exists("my-bucket", "secret.csv")


def test_object_exists_via_uri(mock_s3_client):
    mock_s3_client.head_object.return_value = {}
    s3 = make_s3(mock_s3_client)
    assert s3.object_exists(uri="s3://my-bucket/data.csv") is True
    mock_s3_client.head_object.assert_called_once_with(Bucket="my-bucket", Key="data.csv")


def test_object_exists_via_arn(mock_s3_client):
    mock_s3_client.head_object.return_value = {}
    s3 = make_s3(mock_s3_client)
    assert s3.object_exists(uri=_OBJECT_ARN) is True
    mock_s3_client.head_object.assert_called_once_with(
        Bucket="my-bucket", Key="reports/jan.csv"
    )


def test_object_exists_no_bucket_or_uri_raises(mock_s3_client):
    s3 = make_s3(mock_s3_client)
    with pytest.raises(ValueError, match="Provide uri or both bucket and key"):
        s3.object_exists()


# --- copy_file ---


def test_copy_file_dry_run(mock_s3_client):
    s3 = make_s3(mock_s3_client)
    result = s3.copy_file("src-bucket", "src/key.csv", "dst-bucket", "dst/key.csv")
    assert result == {
        "src_bucket": "src-bucket", "src_key": "src/key.csv",
        "dst_bucket": "dst-bucket", "dst_key": "dst/key.csv",
        "status": "dry_run",
    }
    mock_s3_client.copy_object.assert_not_called()
    assert s3.rows is result


def test_copy_file_commit(mock_s3_client):
    mock_s3_client.copy_object.return_value = {}
    s3 = make_s3(mock_s3_client)
    result = s3.copy_file(
        "src-bucket", "src/key.csv", "dst-bucket", "dst/key.csv", commit=True
    )
    assert result == {
        "src_bucket": "src-bucket", "src_key": "src/key.csv",
        "dst_bucket": "dst-bucket", "dst_key": "dst/key.csv",
        "status": "copied",
    }
    mock_s3_client.copy_object.assert_called_once_with(
        CopySource={"Bucket": "src-bucket", "Key": "src/key.csv"},
        Bucket="dst-bucket",
        Key="dst/key.csv",
    )
    assert s3.rows is result


def test_copy_file_via_uris(mock_s3_client):
    mock_s3_client.copy_object.return_value = {}
    s3 = make_s3(mock_s3_client)
    result = s3.copy_file(
        src_uri="s3://src-bucket/src/key.csv",
        dst_uri="s3://dst-bucket/dst/key.csv",
        commit=True,
    )
    assert result["src_bucket"] == "src-bucket"
    assert result["dst_key"] == "dst/key.csv"
    assert result["status"] == "copied"


def test_copy_file_via_arns(mock_s3_client):
    mock_s3_client.copy_object.return_value = {}
    s3 = make_s3(mock_s3_client)
    result = s3.copy_file(
        src_uri="arn:aws:s3:::src-bucket/src/key.csv",
        dst_uri="arn:aws:s3:::dst-bucket/dst/key.csv",
        commit=True,
    )
    assert result["src_bucket"] == "src-bucket"
    assert result["src_key"] == "src/key.csv"
    assert result["dst_bucket"] == "dst-bucket"
    assert result["dst_key"] == "dst/key.csv"
    assert result["status"] == "copied"


def test_copy_file_no_src_raises(mock_s3_client):
    s3 = make_s3(mock_s3_client)
    with pytest.raises(ValueError, match="src_uri or both src_bucket and src_key"):
        s3.copy_file(dst_bucket="dst-bucket", dst_key="dst/key.csv")


def test_copy_file_no_dst_raises(mock_s3_client):
    s3 = make_s3(mock_s3_client)
    with pytest.raises(ValueError, match="dst_uri or both dst_bucket and dst_key"):
        s3.copy_file("src-bucket", "src/key.csv")
