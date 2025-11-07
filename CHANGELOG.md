# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0] - 2025-11-07

### 🔒 BREAKING CHANGES

Private datasets are now stored in `~/.syftbox/private_datasets/` to ensure they are **NEVER synced** to the SyftBox relay server. This provides true client-side privacy with architectural guarantees.

**Migration Required**: Existing datasets from v0.4.x must be recreated. See the [Migration Guide](./README.md#migration-from-v04x) in the README.

### Changed

- **Private dataset storage location** moved from `~/SyftBox/datasites/<email>/private/datasets/` to `~/.syftbox/private_datasets/<email>/<dataset-name>/`

  - Private datasets are now stored outside the `datasites/` folder and will NOT be synced
  - Provides true client-side privacy - data never leaves your machine
  - No dependency on server-side ACL enforcement

- **Dataset URL structure** updated to reflect new storage locations
  - Private: `syft://<email>/.syftbox/private_datasets/<email>/<dataset-name>`
  - Mock (unchanged): `syft://<email>/public/datasets/<dataset-name>`

### Added

- **Legacy cleanup** - Automatically removes old v0.4.x private datasets when deleting datasets

  - Warning message displayed when old data is found and removed
  - Ensures users don't have duplicate private data in old synced location

- **Integration tests** - New comprehensive tests for private dataset path structure
  - Verifies private datasets are outside `datasites/` folder
  - Confirms path isolation between private and mock datasets
  - Tests URL format correctness
  - Validates multi-user path isolation

### Fixed

- Fixed circular import issue in `dataset_models.py`
- Fixed URL generation to not append source file paths to dataset URLs

## [0.4.2] - 2025-11-06

### Changed

- Removed force recreate keys logic from RDS client
- Updated packages and dependencies
- Refactored UV runtime environment handling

[0.5.0]: https://github.com/OpenMined/syft-rds/compare/v0.4.2...v0.5.0
[0.4.2]: https://github.com/OpenMined/syft-rds/releases/tag/v0.4.2
