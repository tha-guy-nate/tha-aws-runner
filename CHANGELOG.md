# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.3] - 2026-06-27
### Changed
- Enabled mypy `strict = true`; all type annotations across `dynamodb`, `gsi`, `s3`, `ssm`, `cost_tracker`, and `aws_base` updated to satisfy strict checks.

## [0.2.2] - 2026-06-27
### Added
- PyPI version, Python version, and pre-commit badges in README.
- `Changelog` URL in `pyproject.toml` (renders as a PyPI sidebar link).
- GitHub topics set on all 10 tha-* repositories.

## [0.2.1] - 2026-06-27
### Added
- MIT license file with attribution requirement.
- Auto-tag reusable workflow in CI.
- actionlint pre-commit hook for GitHub Actions workflow validation.
### Fixed
- Replaced real AWS account ID and username with sanitized test placeholders.
- Granted `id-token: write` permission in publish workflow for PyPI OIDC.
### Changed
- Inlined publish steps — PyPI Trusted Publishing does not support reusable caller workflows.

## [0.2.0] - 2026-06-25
### Added
- `gsi_hash_key` and `gsi_hash_type` parameters to `ThaGsi` to make `describe_table` optional.
- Pre-commit hooks; centralized publish workflow.

## [0.1.17] - 2026-06-25
### Added
- Per-GSI index breakdown in `DdbCostTracker` (INDEXES mode).
### Changed
- Pinned action versions (checkout v7, setup-uv v8.2.0, upload-artifact v7).
- Trimmed Python classifiers to match CI matrix.

## [0.1.16] - 2026-06-16
### Added
- Python 3.13 and 3.14 classifier and CI support.
### Changed
- Standardized CI and publish workflows.
- Bumped minimum dev dependency floors (pytest ≥ 9.1.0, ruff ≥ 0.15.17, mypy ≥ 2.1.0).
- Added Dependabot for automated updates.

## [0.1.15] - 2026-06-13
### Changed
- `DdbCostTracker` now accepts any `AWSBase` instance (`ThaDdb` or `ThaGsi`).

## [0.1.14] - 2026-06-12
### Added
- `DdbCostTracker` for per-run DynamoDB read/write cost estimation.

## [0.1.13] - 2026-06-08
### Added
- `progress_desc` prefix pattern and `local_path_col` to `batch_download`.

## [0.1.12] - 2026-06-05
### Added
- `skip_statuses` and `status_col` parameters to all batch row methods.

## [0.1.11] - 2026-06-04
### Added
- `ThaGsi` client with GSI query, count, and update support.

## [0.1.10] - 2026-06-04
### Added
- ARN support for DDB, SSM, and S3 resources.
- `ThaS3.object_exists` and `ThaS3.copy_file` methods.

## [0.1.9] - 2026-06-03
### Changed
- Refactored shared helpers into `utils.py`; DDB private helpers moved to static methods.
- Added inline auth to `ThaS3` and `ThaSSM`.

## [0.1.8] - 2026-06-01
### Added
- `table_name_col` parameter to `batch_update_by_pk` and `batch_delete_by_pk`.
- `botocore` as an explicit dependency.

## [0.1.7] - 2026-06-01
### Added
- `ThaS3.download_prefix` for downloading all objects under a key prefix.
### Changed
- Redesigned all batch APIs to be row-based (pass a list of row dicts).

## [0.1.6] - 2026-06-01
### Changed
- Normalized fetch return shape to `{status, message, pk, table, data}` envelope.
- Simplified fetch status enum: `None` = found, `"error"` = missing or AWS error.
- Thread safety improvements across batch methods.

## [0.1.5] - 2026-06-01
### Added
- `ThaS3.batch_download` with `ThreadPoolExecutor`-backed parallel downloads.

## [0.1.4] - 2026-05-31
### Fixed
- Partial results preserved on chunk errors in `batch_fetch_by_pk`.

## [0.1.3] - 2026-05-31
### Added
- `ThaDdb.fetch_by_pk`, `batch_fetch_by_pk`, `batch_delete_by_pk`.
- `ThaS3.list_files`, `delete_file`.
- `ThaSSM.write_param`, `read_params_by_path`.
- `workers` parameter for parallel execution via `ThreadPoolExecutor`.

## [0.1.2] - 2026-05-31
### Added
- `commit` parameter to write methods for dry-run support.
- `batch_update_by_pk` method on `ThaDdb`.
### Changed
- Renamed `batch_put` to `batch_write`.

## [0.1.1] - 2026-05-30
### Changed
- `fetch_by_pk` now nests result by table name.

## [0.1.0] - 2026-05-30
### Added
- Initial release with `ThaDdb`, `ThaS3`, and `ThaSSM` clients.
