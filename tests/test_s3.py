from io import BytesIO
from unittest.mock import MagicMock

import pytest

from tha_aws_runner.s3 import ThaS3, _parse_s3_uri


def make_s3(mock_client: MagicMock) -> ThaS3:
    s3 = ThaS3(region="us-east-1")
    s3._s3 = mock_client
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
