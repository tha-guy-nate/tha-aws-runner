from unittest.mock import MagicMock

from tha_aws_runner.ssm import ThaSSM


def test_read_param_happy():
    mock_client = MagicMock()
    mock_client.get_parameter.return_value = {"Parameter": {"Value": "secret-value"}}

    ssm = ThaSSM(region="us-east-1")
    ssm._thread_local.ssm = mock_client

    result = ssm.read_param("/my/param")
    assert result == "secret-value"
    assert ssm.rows == "secret-value"
    mock_client.get_parameter.assert_called_once_with(Name="/my/param", WithDecryption=False)


def test_read_param_with_decryption():
    mock_client = MagicMock()
    mock_client.get_parameter.return_value = {"Parameter": {"Value": "decrypted"}}

    ssm = ThaSSM()
    ssm._thread_local.ssm = mock_client

    result = ssm.read_param("/secure/param", with_decryption=True)
    assert result == "decrypted"
    mock_client.get_parameter.assert_called_once_with(Name="/secure/param", WithDecryption=True)


def test_read_param_uses_injected_client():
    mock_client = MagicMock()
    mock_client.get_parameter.return_value = {"Parameter": {"Value": "injected"}}

    other_client = MagicMock()
    ssm = ThaSSM()
    ssm._ssm = other_client  # this should be bypassed

    result = ssm.read_param("/param", ssm=mock_client)
    assert result == "injected"
    other_client.get_parameter.assert_not_called()


# --- read_params_by_path ---


def test_read_params_by_path_happy():
    mock_client = MagicMock()
    mock_client.get_paginator.return_value.paginate.return_value = [
        {
            "Parameters": [
                {"Name": "/app/db_host", "Value": "localhost"},
                {"Name": "/app/db_port", "Value": "5432"},
            ]
        }
    ]
    ssm = ThaSSM()
    ssm._thread_local.ssm = mock_client
    result = ssm.read_params_by_path("/app")
    assert result == {"/app/db_host": "localhost", "/app/db_port": "5432"}
    assert ssm.rows is result
    mock_client.get_paginator.assert_called_once_with("get_parameters_by_path")


def test_read_params_by_path_empty():
    mock_client = MagicMock()
    mock_client.get_paginator.return_value.paginate.return_value = [{"Parameters": []}]
    ssm = ThaSSM()
    ssm._thread_local.ssm = mock_client
    result = ssm.read_params_by_path("/missing")
    assert result == {}


def test_read_params_by_path_multi_page():
    mock_client = MagicMock()
    mock_client.get_paginator.return_value.paginate.return_value = [
        {"Parameters": [{"Name": "/app/a", "Value": "1"}]},
        {"Parameters": [{"Name": "/app/b", "Value": "2"}]},
    ]
    ssm = ThaSSM()
    ssm._thread_local.ssm = mock_client
    result = ssm.read_params_by_path("/app")
    assert result == {"/app/a": "1", "/app/b": "2"}


# --- write_param ---


def test_write_param_dry_run():
    mock_client = MagicMock()
    ssm = ThaSSM()
    ssm._thread_local.ssm = mock_client
    result = ssm.write_param("/app/key", "value")
    assert result == {"path": "/app/key", "status": "dry_run"}
    mock_client.put_parameter.assert_not_called()
    assert ssm.rows is result


def test_write_param_commit():
    mock_client = MagicMock()
    mock_client.put_parameter.return_value = {}
    ssm = ThaSSM()
    ssm._thread_local.ssm = mock_client
    result = ssm.write_param("/app/key", "value", commit=True)
    assert result == {"path": "/app/key", "status": "written"}
    mock_client.put_parameter.assert_called_once_with(
        Name="/app/key", Value="value", Type="String", Overwrite=True
    )
    assert ssm.rows is result


def test_write_param_custom_type_no_overwrite():
    mock_client = MagicMock()
    mock_client.put_parameter.return_value = {}
    ssm = ThaSSM()
    ssm._thread_local.ssm = mock_client
    ssm.write_param(
        "/app/secret", "s3cr3t", param_type="SecureString", overwrite=False, commit=True
    )
    mock_client.put_parameter.assert_called_once_with(
        Name="/app/secret", Value="s3cr3t", Type="SecureString", Overwrite=False
    )


# --- ARN resolution ---

_PARAM_ARN = "arn:aws:ssm:us-east-1:123456789012:parameter/my/app/secret"


def test_resolve_param_path_plain():
    assert ThaSSM._resolve_param_path("/my/param") == "/my/param"


def test_resolve_param_path_arn():
    assert ThaSSM._resolve_param_path(_PARAM_ARN) == "/my/app/secret"


def test_read_param_arn():
    mock_client = MagicMock()
    mock_client.get_parameter.return_value = {"Parameter": {"Value": "secret-value"}}
    ssm = ThaSSM()
    ssm._thread_local.ssm = mock_client
    result = ssm.read_param(_PARAM_ARN)
    assert result == "secret-value"
    mock_client.get_parameter.assert_called_once_with(Name="/my/app/secret", WithDecryption=False)


def test_write_param_arn():
    mock_client = MagicMock()
    mock_client.put_parameter.return_value = {}
    ssm = ThaSSM()
    ssm._thread_local.ssm = mock_client
    result = ssm.write_param(_PARAM_ARN, "value", commit=True)
    assert result == {"path": "/my/app/secret", "status": "written"}
    mock_client.put_parameter.assert_called_once_with(
        Name="/my/app/secret", Value="value", Type="String", Overwrite=True
    )
