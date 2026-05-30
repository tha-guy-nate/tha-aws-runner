from tha_aws_runner.aws_base import cli_auth_check, parse_assumed_role_arn


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
