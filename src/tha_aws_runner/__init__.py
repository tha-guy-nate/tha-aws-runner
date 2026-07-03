"""tha-aws-runner: typed boto3 wrapper for DynamoDB, S3, and SSM."""

from tha_aws_runner.aws_base import AWSBase, AWSClients
from tha_aws_runner.cost_tracker import DdbCostTracker
from tha_aws_runner.dynamodb import ThaDdb
from tha_aws_runner.errors import AwsError
from tha_aws_runner.gsi import BatchCountResult, BatchQueryResult, BatchUpdateResult, ThaGsi
from tha_aws_runner.s3 import ThaS3
from tha_aws_runner.ssm import ThaSSM
from tha_aws_runner.utils import cli_auth_check, current_identity, parse_arn, parse_assumed_role_arn

__version__ = "0.2.6"
__all__ = [
    "AWSBase",
    "AWSClients",
    "AwsError",
    "BatchCountResult",
    "BatchQueryResult",
    "BatchUpdateResult",
    "DdbCostTracker",
    "ThaDdb",
    "ThaGsi",
    "ThaS3",
    "ThaSSM",
    "cli_auth_check",
    "current_identity",
    "parse_arn",
    "parse_assumed_role_arn",
]
