from typing import Any

from tha_aws_runner.aws_base import AWSClients


def parse_arn(arn: str) -> dict[str, str | None]:
    """Parse any AWS ARN into its components.

    Returns {"partition", "service", "region", "account_id", "resource_type", "resource_id"}.
    resource_type is None for ARNs where the resource is a bare ID (e.g. SNS topics).
    All values are None if the ARN is malformed.
    """
    empty: dict[str, str | None] = {
        "partition": None,
        "service": None,
        "region": None,
        "account_id": None,
        "resource_type": None,
        "resource_id": None,
    }
    try:
        parts = arn.split(":", 5)
        if len(parts) < 6 or parts[0] != "arn":
            return empty
        resource = parts[5]
        if "/" in resource:
            resource_type, _, resource_id = resource.partition("/")
        elif ":" in resource:
            resource_type, _, resource_id = resource.partition(":")
        else:
            resource_type = None
            resource_id = resource
        return {
            "partition": parts[1] or None,
            "service": parts[2] or None,
            "region": parts[3] or None,
            "account_id": parts[4] or None,
            "resource_type": resource_type or None,
            "resource_id": resource_id or None,
        }
    except (IndexError, AttributeError):
        return empty


def parse_assumed_role_arn(arn: str) -> tuple[str | None, str | None, str | None]:
    try:
        arn_parts = arn.split(":")
        account_id = arn_parts[4]
        resource = arn_parts[5]
        resource_parts = resource.split("/")
        role_name = resource_parts[1]
        session_name = resource_parts[2]
        return account_id, role_name, session_name
    except (IndexError, AttributeError):
        return None, None, None


def cli_auth_check(
    account_id: str | None,
    role_name: str | None,
    allowed_account_id: str | list[str],
    allowed_aws_role: str | list[str],
) -> bool:
    allowed_accounts = (
        {allowed_account_id} if isinstance(allowed_account_id, str) else set(allowed_account_id)
    )
    allowed_roles = (
        {allowed_aws_role} if isinstance(allowed_aws_role, str) else set(allowed_aws_role)
    )

    if account_id not in allowed_accounts or role_name not in allowed_roles:
        print(
            f"Current AWS identity:\n"
            f"  Account: {account_id}\n"
            f"  Role:    {role_name}\n\n"
            f"Expected:\n"
            f"  Account: {allowed_accounts}\n"
            f"  Role:    {allowed_roles}"
        )
        return False
    return True


def current_identity(
    *, region: str | None = None, profile: str | None = None
) -> tuple[Any, str | None, str | None, str | None]:
    aws = AWSClients(region=region, profile=profile)
    identity = aws.sts().get_caller_identity()
    account_id, role_name, session_name = parse_assumed_role_arn(identity["Arn"])
    return identity, account_id, role_name, session_name
