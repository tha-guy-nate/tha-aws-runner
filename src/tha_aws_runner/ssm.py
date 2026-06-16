from collections.abc import Callable
from typing import Any

from tha_aws_runner.aws_base import AWSBase
from tha_aws_runner.utils import parse_arn


class ThaSSM(AWSBase):
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
        super().__init__(
            status_cb=status_cb,
            mode=mode,
            region=region,
            profile=profile,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            aws_session_token=aws_session_token,
        )

    @staticmethod
    def _resolve_param_path(path: str) -> str:
        if not path.startswith("arn:"):
            return path
        resource_id = parse_arn(path).get("resource_id")
        if not resource_id:
            raise ValueError(f"Could not extract parameter path from ARN: {path!r}")
        return "/" + resource_id

    def _client(self, ssm: Any = None) -> Any:
        if ssm is not None:
            return ssm
        if not hasattr(self._thread_local, "ssm"):
            self._thread_local.ssm = self._thread_clients().ssm()
        return self._thread_local.ssm  # type: ignore[no-any-return]

    def read_param(
        self,
        path: str,
        *,
        with_decryption: bool = False,
        ssm: Any = None,
    ) -> str:
        path = self._resolve_param_path(path)
        ssm_client = self._client(ssm)
        response = ssm_client.get_parameter(Name=path, WithDecryption=with_decryption)
        value: str = response["Parameter"]["Value"]
        self.rows = value
        return value

    def read_params_by_path(
        self,
        path_prefix: str,
        *,
        with_decryption: bool = False,
        ssm: Any = None,
    ) -> dict[str, str]:
        ssm_client = self._client(ssm)
        params: dict[str, str] = {}
        paginator = ssm_client.get_paginator("get_parameters_by_path")
        for page in paginator.paginate(
            Path=path_prefix, WithDecryption=with_decryption, Recursive=True
        ):
            for param in page.get("Parameters", []):
                params[param["Name"]] = param["Value"]
        self.rows = params
        return params

    def write_param(
        self,
        path: str,
        value: str,
        *,
        param_type: str = "String",
        overwrite: bool = True,
        commit: bool = False,
        ssm: Any = None,
    ) -> dict:
        path = self._resolve_param_path(path)
        if not commit:
            result: dict[str, Any] = {"path": path, "status": "dry_run"}
            self.rows = result
            return result

        ssm_client = self._client(ssm)
        ssm_client.put_parameter(Name=path, Value=value, Type=param_type, Overwrite=overwrite)
        result = {"path": path, "status": "written"}
        self.rows = result
        return result
