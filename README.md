# RDS

## Requirements

- [just](https://github.com/casey/just?tab=readme-ov-file#installation)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

## Quick Install

Available on [Pypi](https://pypi.org/project/syft-rds/). Install with

```
uv pip install syft-rds
```

Or you can clone the repo and set the dev Python environment with all dependencies:

```bash
just setup
```

## Getting Started

### Run the Demo

The notebook `notebooks/quickstart/full_flow.ipynb` contains a complete example of the RDS workflow from both the Data Owner (DO) and Data Scientist (DS) perspectives.

This demo uses a mock in-memory stack that simulates SyftBox functionality locally - no external services required.

To run the demo:

```bash
just jupyter
```

Then open `notebooks/quickstart/full_flow.ipynb` and run through the cells.

**The demo covers a basic remote data science workflow:**

1. **Data Owner** creates a dataset with private and mock (public) data
2. **Data Scientist** explores available datasets (can only see mock data)
3. **Data Scientist** submits code to run on private data
4. **Data Owner** reviews and runs the code on private data
5. **Data Owner** shares the results
6. **Data Scientist** views the output

## Private Dataset Storage

### Storage Locations

**Private datasets** are stored in `~/.syftbox/private_datasets/<email>/<dataset-name>/` and are **NEVER synced** to the SyftBox relay server. This ensures true client-side privacy - your private data never leaves your machine.

**Mock (public) datasets** are stored in `~/SyftBox/datasites/<email>/public/datasets/` and **ARE synced** to the relay server, allowing other users to explore your dataset structure and submit job requests.

```
~/.syftbox/
  private_datasets/
    your-email@example.com/
      my-dataset/           # Your private data (NEVER synced anywhere)
        data.csv
        ...

~/SyftBox/
  datasites/
    your-email@example.com/
      public/
        datasets/
          my-dataset/         # Your mock data (synced to the SyftBox server and other datasites)
            mock_data.csv
            README.md
```

### Migration from v0.4.x

⚠️ **BREAKING CHANGE in syft-rds v0.5.0**

If you have existing datasets created with syft-rds v0.4.x, you'll need to recreate them:

1. Note your existing dataset names
2. Upgrade to syft-rds v0.5.0+
3. Re-create datasets using the same private data source
4. The new version will automatically use the new location

Old private data in `datasites/<email>/private/` will not interfere and will be automatically cleaned up when you delete the datasets.

## Development

### Running Tests

```bash
# Run all tests
just test

# Run specific test suites
just test-unit
just test-integration
just test-notebooks
```

### Building

```bash
# Build the wheel package
just build

# Bump version (patch/minor/major)
just bump patch
```

### Cleaning Up

Remove generated files and directories:

```bash
just clean
```

## Available Commands

See all available commands:

```bash
just --list
```
