from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_ddb_client():
    return MagicMock()


@pytest.fixture
def mock_ssm_client():
    return MagicMock()


@pytest.fixture
def mock_s3_client():
    return MagicMock()
