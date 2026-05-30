from collections.abc import Callable
from typing import Any

from tha_aws_runner.aws_base import AWSBase


class ThaSSM(AWSBase):
    def __init__(
        self,
        *,
        status_cb: Callable[[str], None] | None = None,
        mode: str = "app",
        region: str | None = None,
        profile: str | None = None,
    ) -> None:
        super().__init__(status_cb=status_cb, mode=mode, region=region, profile=profile)
        self._ssm: Any = None

    def _client(self, ssm: Any = None) -> Any:
        if ssm is not None:
            return ssm
        if self._ssm is None:
            self._ssm = self.clients.ssm()
        return self._ssm

    def read_param(
        self,
        path: str,
        *,
        with_decryption: bool = False,
        ssm: Any = None,
    ) -> str:
        ssm = self._client(ssm)
        response = ssm.get_parameter(Name=path, WithDecryption=with_decryption)
        value: str = response["Parameter"]["Value"]
        self.rows = value
        return value
