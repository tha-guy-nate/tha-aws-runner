import shutil
import threading
from collections.abc import Callable, Iterable
from typing import Any, TypeVar

import boto3
from tqdm import tqdm

T = TypeVar("T")


class AWSClients:
    def __init__(
        self,
        *,
        region: str | None = None,
        profile: str | None = None,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        aws_session_token: str | None = None,
    ) -> None:
        self.session = boto3.Session(
            profile_name=profile,
            region_name=region,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            aws_session_token=aws_session_token,
        )

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


class AWSBase:
    def __init__(
        self,
        *,
        status_cb: Callable[[str], None] | None = None,
        mode: str = "app",
        region: str | None = None,
        profile: str | None = None,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        aws_session_token: str | None = None,
    ) -> None:
        self.status_cb = status_cb
        self.mode = mode
        self._region = region
        self._profile = profile
        self._aws_access_key_id = aws_access_key_id
        self._aws_secret_access_key = aws_secret_access_key
        self._aws_session_token = aws_session_token
        self.clients = AWSClients(
            region=region,
            profile=profile,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            aws_session_token=aws_session_token,
        )
        self._thread_local = threading.local()
        self._client_lock = threading.Lock()
        self.rows: Any = None

    def _thread_clients(self) -> AWSClients:
        """Return a per-thread AWSClients instance (one session per thread)."""
        if not hasattr(self._thread_local, "clients"):
            self._thread_local.clients = AWSClients(
                region=self._region,
                profile=self._profile,
                aws_access_key_id=self._aws_access_key_id,
                aws_secret_access_key=self._aws_secret_access_key,
                aws_session_token=self._aws_session_token,
            )
        clients: AWSClients = self._thread_local.clients
        return clients

    def _progress_iter(
        self,
        iterable: Iterable[T],
        *,
        total: int | None = None,
        desc: str | None = None,
        show_progress: bool = False,
    ) -> Iterable[T]:
        if show_progress or self.mode == "cli":
            ncols = min(shutil.get_terminal_size(fallback=(85, 24)).columns, 85)
            return tqdm(iterable, total=total, desc=desc, ncols=ncols)  # type: ignore[no-any-return]
        return iterable

    def _progress_update(self, message: str) -> None:
        if self.mode != "cli" and self.status_cb is not None:
            self.status_cb(message)
