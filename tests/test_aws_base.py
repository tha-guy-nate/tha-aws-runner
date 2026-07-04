from unittest.mock import MagicMock, patch

import pytest

from tha_aws_runner.aws_base import AWSBase, AWSClients
from tha_aws_runner.utils import cli_auth_check, parse_arn, parse_assumed_role_arn


def test_parse_assumed_role_arn_happy():
    arn = "arn:aws:sts::123456789012:assumed-role/my_role/test-user"
    account_id, role_name, session_name = parse_assumed_role_arn(arn)
    assert account_id == "123456789012"
    assert role_name == "my_role"
    assert session_name == "test-user"


def test_parse_assumed_role_arn_malformed():
    account_id, role_name, session_name = parse_assumed_role_arn("not-an-arn")
    assert account_id is None
    assert role_name is None
    assert session_name is None


def test_cli_auth_check_passes():
    assert cli_auth_check("123456789", "my_role", "123456789", "my_role") is True


def test_cli_auth_check_fails_account(capsys):
    result = cli_auth_check("wrong_account", "my_role", "123456789", "my_role")
    assert result is False
    assert "Expected" in capsys.readouterr().out


def test_cli_auth_check_fails_role(capsys):
    result = cli_auth_check("123456789", "wrong_role", "123456789", "my_role")
    assert result is False


def test_cli_auth_check_list_accounts():
    assert cli_auth_check("999", "role", ["123", "999"], "role") is True


def test_cli_auth_check_list_roles():
    assert cli_auth_check("123", "role_b", "123", ["role_a", "role_b"]) is True


# --- parse_arn ---


def test_parse_arn_ec2_instance():
    arn = "arn:aws:ec2:us-east-1:123456789012:instance/i-0abcdef1234567890"
    result = parse_arn(arn)
    assert result["partition"] == "aws"
    assert result["service"] == "ec2"
    assert result["region"] == "us-east-1"
    assert result["account_id"] == "123456789012"
    assert result["resource_type"] == "instance"
    assert result["resource_id"] == "i-0abcdef1234567890"


def test_parse_arn_sns_topic():
    arn = "arn:aws:sns:us-east-1:123456789012:MyTopic"
    result = parse_arn(arn)
    assert result["service"] == "sns"
    assert result["resource_type"] is None
    assert result["resource_id"] == "MyTopic"


def test_parse_arn_ssm_parameter():
    arn = "arn:aws:ssm:us-east-1:123456789012:parameter/my/param"
    result = parse_arn(arn)
    assert result["service"] == "ssm"
    assert result["resource_type"] == "parameter"
    assert result["resource_id"] == "my/param"


def test_parse_arn_dynamodb_table():
    arn = "arn:aws:dynamodb:us-east-1:123456789012:table/MyTable"
    result = parse_arn(arn)
    assert result["service"] == "dynamodb"
    assert result["resource_type"] == "table"
    assert result["resource_id"] == "MyTable"


def test_parse_arn_malformed():
    result = parse_arn("not-an-arn")
    assert all(v is None for v in result.values())


def test_parse_arn_wrong_prefix():
    result = parse_arn("aws:iam::123:role/MyRole")
    assert all(v is None for v in result.values())


# --- inline auth ---


def test_aws_clients_inline_creds_passed_to_boto3():
    with patch("boto3.Session") as mock_session:
        AWSClients(
            aws_access_key_id="AKIA123",
            aws_secret_access_key="secret",
            aws_session_token="token",
            region="us-east-1",
        )
    mock_session.assert_called_once_with(
        profile_name=None,
        region_name="us-east-1",
        aws_access_key_id="AKIA123",
        aws_secret_access_key="secret",
        aws_session_token="token",
    )


def test_aws_clients_no_inline_creds_passes_none():
    with patch("boto3.Session") as mock_session:
        AWSClients(region="us-west-2")
    call_kwargs = mock_session.call_args.kwargs
    assert call_kwargs["aws_access_key_id"] is None
    assert call_kwargs["aws_secret_access_key"] is None
    assert call_kwargs["aws_session_token"] is None


# --- AWSClients service accessors ---

_CLIENT_ACCESSORS = {
    "sts": "sts",
    "iam": "iam",
    "rds": "rds",
    "s3": "s3",
    "ssm": "ssm",
    "secretsmanager": "secretsmanager",
    "lambda_": "lambda",
    "ec2": "ec2",
    "ecs": "ecs",
    "ecr": "ecr",
    "cloudwatch": "cloudwatch",
    "logs": "logs",
    "sns": "sns",
    "sqs": "sqs",
    "eventbridge": "events",
    "athena": "athena",
    "glue": "glue",
    "kinesis": "kinesis",
    "dynamodb": "dynamodb",
}

_RESOURCE_ACCESSORS = {
    "dynamodb_resource": "dynamodb",
    "s3_resource": "s3",
}


@pytest.mark.parametrize(("method_name", "service_name"), _CLIENT_ACCESSORS.items())
def test_client_accessor_requests_correct_service(method_name: str, service_name: str) -> None:
    with patch("boto3.Session") as mock_session_cls:
        mock_session = mock_session_cls.return_value
        clients = AWSClients()
        getattr(clients, method_name)()
    mock_session.client.assert_called_once_with(service_name)


@pytest.mark.parametrize(("method_name", "service_name"), _RESOURCE_ACCESSORS.items())
def test_resource_accessor_requests_correct_service(method_name: str, service_name: str) -> None:
    with patch("boto3.Session") as mock_session_cls:
        mock_session = mock_session_cls.return_value
        clients = AWSClients()
        getattr(clients, method_name)()
    mock_session.resource.assert_called_once_with(service_name)


# --- AWSBase ---


def test_thread_clients_caches_per_thread() -> None:
    with patch("boto3.Session"):
        base = AWSBase()
        first = base._thread_clients()
        second = base._thread_clients()
    assert first is second
    assert isinstance(first, AWSClients)


def test_progress_update_calls_status_cb_in_app_mode() -> None:
    status_cb = MagicMock()
    with patch("boto3.Session"):
        base = AWSBase(status_cb=status_cb, mode="app")
        base._progress_update("hello")
    status_cb.assert_called_once_with("hello")


def test_progress_update_skips_status_cb_in_cli_mode() -> None:
    status_cb = MagicMock()
    with patch("boto3.Session"):
        base = AWSBase(status_cb=status_cb, mode="cli")
        base._progress_update("hello")
    status_cb.assert_not_called()
