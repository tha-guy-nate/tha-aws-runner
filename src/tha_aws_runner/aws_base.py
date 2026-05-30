import shutil
from collections.abc import Callable, Iterable
from typing import Any, TypeVar

import boto3
from tqdm import tqdm

T = TypeVar("T")


class AWSClients:
    def __init__(self, *, region: str | None = None, profile: str | None = None) -> None:
        self.session = boto3.Session(profile_name=profile, region_name=region)

    def sts(self) -> Any:
        return self.session.client("sts")

    def iam(self) -> Any:
        return self.session.client("iam")

    def dynamodb(self) -> Any:
        return self.session.client("dynamodb")

    def dynamodb_resource(self) -> Any:
        return self.session.resource("dynamodb")

    def rds(self) -> Any:
        return self.session.client("rds")

    def s3(self) -> Any:
        return self.session.client("s3")

    def s3_resource(self) -> Any:
        return self.session.resource("s3")

    def ssm(self) -> Any:
        return self.session.client("ssm")

    def secretsmanager(self) -> Any:
        return self.session.client("secretsmanager")

    def lambda_(self) -> Any:
        return self.session.client("lambda")

    def ec2(self) -> Any:
        return self.session.client("ec2")

    def ecs(self) -> Any:
        return self.session.client("ecs")

    def ecr(self) -> Any:
        return self.session.client("ecr")

    def cloudwatch(self) -> Any:
        return self.session.client("cloudwatch")

    def logs(self) -> Any:
        return self.session.client("logs")

    def sns(self) -> Any:
        return self.session.client("sns")

    def sqs(self) -> Any:
        return self.session.client("sqs")

    def eventbridge(self) -> Any:
        return self.session.client("events")

    def athena(self) -> Any:
        return self.session.client("athena")

    def glue(self) -> Any:
        return self.session.client("glue")

    def kinesis(self) -> Any:
        return self.session.client("kinesis")


def current_identity(
    *, region: str | None = None, profile: str | None = None
) -> tuple[Any, str | None, str | None, str | None]:
    aws = AWSClients(region=region, profile=profile)
    identity = aws.sts().get_caller_identity()
    account_id, role_name, session_name = parse_assumed_role_arn(identity["Arn"])
    return identity, account_id, role_name, session_name


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


class AWSBase:
    def __init__(
        self,
        *,
        status_cb: Callable[[str], None] | None = None,
        mode: str = "app",
        region: str | None = None,
        profile: str | None = None,
    ) -> None:
        self.status_cb = status_cb
        self.mode = mode
        self.clients = AWSClients(region=region, profile=profile)
        self.rows: Any = None

    def _progress_iter(
        self,
        iterable: Iterable[T],
        *,
        total: int | None = None,
        desc: str | None = None,
    ) -> Iterable[T]:
        if self.mode == "cli":
            ncols = min(shutil.get_terminal_size(fallback=(85, 24)).columns, 85)
            return tqdm(iterable, total=total, desc=desc, ncols=ncols)  # type: ignore[return-value]
        return iterable

    def _progress_update(self, message: str) -> None:
        if self.mode != "cli" and self.status_cb is not None:
            self.status_cb(message)
