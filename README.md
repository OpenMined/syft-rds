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
