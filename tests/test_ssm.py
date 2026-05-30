from unittest.mock import MagicMock

from tha_aws_runner.ssm import ThaSSM


def test_read_param_happy():
    mock_client = MagicMock()
    mock_client.get_parameter.return_value = {"Parameter": {"Value": "secret-value"}}

    ssm = ThaSSM(region="us-east-1")
    ssm._ssm = mock_client

    result = ssm.read_param("/my/param")
    assert result == "secret-value"
    assert ssm.rows == "secret-value"
    mock_client.get_parameter.assert_called_once_with(Name="/my/param", WithDecryption=False)


def test_read_param_with_decryption():
    mock_client = MagicMock()
    mock_client.get_parameter.return_value = {"Parameter": {"Value": "decrypted"}}

    ssm = ThaSSM()
    ssm._ssm = mock_client

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
