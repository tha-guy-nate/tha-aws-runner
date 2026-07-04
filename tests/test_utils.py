from unittest.mock import MagicMock, patch

import pytest

from tha_aws_runner.utils import _to_ddb_attr, current_identity, parse_arn

# ---------------------------------------------------------------------------
# _to_ddb_attr
# ---------------------------------------------------------------------------


def test_to_ddb_attr_unwraps_matching_typed_value():
    assert _to_ddb_attr({"N": "5"}, "N") == {"N": "5"}


def test_to_ddb_attr_raises_on_mismatched_typed_value():
    with pytest.raises(ValueError, match="does not match update_type"):
        _to_ddb_attr({"N": "5"}, "S")


def test_to_ddb_attr_bool_true_string():
    assert _to_ddb_attr("yes", "BOOL") == {"BOOL": True}


def test_to_ddb_attr_bool_false_string():
    assert _to_ddb_attr("no", "BOOL") == {"BOOL": False}


def test_to_ddb_attr_s_none_raises():
    with pytest.raises(ValueError, match="S does not allow None"):
        _to_ddb_attr(None, "S")


def test_to_ddb_attr_n_none_raises():
    with pytest.raises(ValueError, match="N does not allow None"):
        _to_ddb_attr(None, "N")


def test_to_ddb_attr_n_numeric_string():
    assert _to_ddb_attr(" 42 ", "N") == {"N": "42"}


def test_to_ddb_attr_n_invalid_type_raises():
    with pytest.raises(ValueError, match="N requires int/float or numeric string"):
        _to_ddb_attr([1, 2], "N")


def test_to_ddb_attr_null_invalid_raises():
    with pytest.raises(ValueError, match="NULL expects None/blank"):
        _to_ddb_attr("not blank", "NULL")


def test_to_ddb_attr_unsupported_update_type_raises():
    with pytest.raises(ValueError, match="Unsupported update_type"):
        _to_ddb_attr("x", "L")


# ---------------------------------------------------------------------------
# parse_arn
# ---------------------------------------------------------------------------


def test_parse_arn_colon_delimited_resource():
    arn = "arn:aws:cloudwatch:us-east-1:123456789012:alarm:MyAlarm"
    result = parse_arn(arn)
    assert result["resource_type"] == "alarm"
    assert result["resource_id"] == "MyAlarm"


def test_parse_arn_non_string_input_returns_empty():
    result = parse_arn(None)  # type: ignore[arg-type]
    assert all(v is None for v in result.values())


# ---------------------------------------------------------------------------
# current_identity
# ---------------------------------------------------------------------------


def test_current_identity_parses_caller_identity():
    mock_clients = MagicMock()
    mock_clients.sts.return_value.get_caller_identity.return_value = {
        "Arn": "arn:aws:sts::123456789012:assumed-role/my_role/test-user"
    }

    with patch("tha_aws_runner.utils.AWSClients", return_value=mock_clients) as mock_cls:
        identity, account_id, role_name, session_name = current_identity(
            region="us-east-1", profile="default"
        )

    mock_cls.assert_called_once_with(region="us-east-1", profile="default")
    assert identity == {"Arn": "arn:aws:sts::123456789012:assumed-role/my_role/test-user"}
    assert account_id == "123456789012"
    assert role_name == "my_role"
    assert session_name == "test-user"
