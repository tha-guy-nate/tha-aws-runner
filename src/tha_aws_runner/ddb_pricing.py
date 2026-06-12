# DynamoDB on-demand pricing per RCU/WCU by region.
# Source: https://aws.amazon.com/dynamodb/pricing/on-demand/ (verified 2025-06)
# Values are per single request unit (not per million).

_READ_PER_RCU: dict[str, float] = {
    "us-east-1": 0.25 / 1_000_000,
    "us-east-2": 0.25 / 1_000_000,
    "us-west-1": 0.25 / 1_000_000,
    "us-west-2": 0.25 / 1_000_000,
    "ca-central-1": 0.275 / 1_000_000,
    "eu-west-1": 0.2972 / 1_000_000,
    "eu-west-2": 0.2972 / 1_000_000,
    "eu-west-3": 0.2972 / 1_000_000,
    "eu-central-1": 0.2838 / 1_000_000,
    "eu-north-1": 0.2838 / 1_000_000,
    "ap-southeast-1": 0.2972 / 1_000_000,
    "ap-southeast-2": 0.2972 / 1_000_000,
    "ap-northeast-1": 0.3235 / 1_000_000,
    "ap-northeast-2": 0.2972 / 1_000_000,
    "ap-south-1": 0.2838 / 1_000_000,
    "sa-east-1": 0.4180 / 1_000_000,
}

_WRITE_PER_WCU: dict[str, float] = {
    "us-east-1": 1.25 / 1_000_000,
    "us-east-2": 1.25 / 1_000_000,
    "us-west-1": 1.25 / 1_000_000,
    "us-west-2": 1.25 / 1_000_000,
    "ca-central-1": 1.375 / 1_000_000,
    "eu-west-1": 1.4872 / 1_000_000,
    "eu-west-2": 1.4872 / 1_000_000,
    "eu-west-3": 1.4872 / 1_000_000,
    "eu-central-1": 1.4191 / 1_000_000,
    "eu-north-1": 1.4191 / 1_000_000,
    "ap-southeast-1": 1.4872 / 1_000_000,
    "ap-southeast-2": 1.4872 / 1_000_000,
    "ap-northeast-1": 1.6175 / 1_000_000,
    "ap-northeast-2": 1.4872 / 1_000_000,
    "ap-south-1": 1.4191 / 1_000_000,
    "sa-east-1": 2.0900 / 1_000_000,
}

_DEFAULT_REGION = "us-east-1"


def rcu_price(region: str) -> float:
    return _READ_PER_RCU.get(region, _READ_PER_RCU[_DEFAULT_REGION])


def wcu_price(region: str) -> float:
    return _WRITE_PER_WCU.get(region, _WRITE_PER_WCU[_DEFAULT_REGION])
