"""tha-aws-runner: typed boto3 wrapper for DynamoDB, S3, and SSM."""

from tha_aws_runner.aws_base import (
    AWSBase,
    AWSClients,
    cli_auth_check,
    current_identity,
    parse_assumed_role_arn,
)
from tha_aws_runner.dynamodb import ThaDdb
from tha_aws_runner.errors import AwsError
from tha_aws_runner.s3 import ThaS3
from tha_aws_runner.ssm import ThaSSM

__version__ = "0.1.4"
__all__ = [
    "AWSBase",
    "AWSClients",
    "AwsError",
    "ThaDdb",
    "ThaS3",
    "ThaSSM",
    "cli_auth_check",
    "current_identity",
    "parse_assumed_role_arn",
]
