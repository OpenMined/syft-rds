set dotenv-load := true

# ---------------------------------------------------------------------------------------------------------------------
# Private vars

_red := '\033[1;31m'
_cyan := '\033[1;36m'
_green := '\033[1;32m'
_yellow := '\033[1;33m'
_nc := '\033[0m'
_test_workers := env_var_or_default('TEST_WORKERS', 'auto')
_test_verbosity := env_var_or_default('TEST_VERBOSE', 'sq')

# ---------------------------------------------------------------------------------------------------------------------
# Aliases


# ---------------------------------------------------------------------------------------------------------------------

@default:
    just --list

# ---------------------------------------------------------------------------------------------------------------------

# setup python environment
[group('utils')]
setup:
    #!/bin/bash
    uv venv
    uv sync --all-groups
    source .venv/bin/activate
    echo "{{ _green }}✓ Setup complete!{{ _nc }}"

# run jupyter lab
[group('utils')]
jupyter: setup
    #!/bin/bash
    source .venv/bin/activate
    jupyter lab

# ---------------------------------------------------------------------------------------------------------------------

# remove all local files & directories
[group('utils')]
clean:
    #!/bin/sh
    echo "{{ _cyan }}Cleaning up local files and directories...{{ _nc }}"

    for dir in ./.clients ./dist ./.e2e ./.logs ./.pytest_cache; do
        if [ -d "$dir" ]; then
            echo "  {{ _red }}✗{{ _nc }} Removing $dir"
            rm -rf "$dir"
        fi
    done

    remove_dirs() {
        dir_name=$1
        dirs=$(find . -type d -name "$dir_name" 2>/dev/null)
        if [ -n "$dirs" ]; then
            echo "$dirs" | while read -r dir; do
                echo "  {{ _red }}✗{{ _nc }} Removing $dir"
                rm -rf "$dir"
            done
        fi
    }
    # Remove directories by name pattern
    remove_dirs ".server"
    remove_dirs ".clients"
    remove_dirs ".syftbox"
    remove_dirs "local_syftbox_network"
    remove_dirs "__pycache__"
    remove_dirs ".ipynb_checkpoints"

    echo "{{ _green }}✓ Clean complete!{{ _nc }}"

# ---------------------------------------------------------------------------------------------------------------------

[group('test')]
setup-test-env:
    #!/bin/sh
    if [ ! -d ".venv" ]; then
        uv venv
    fi
    uv sync --all-groups --cache-dir=.uv-cache

[group('test')]
test-unit: setup-test-env
    #!/bin/sh
    echo "{{ _cyan }}Running unit tests {{ _nc }}"
    uv run --with "pytest-xdist" pytest -{{ _test_verbosity }} --color=yes -n {{ _test_workers }} tests/unit/

[group('test')]
test-integration: setup-test-env
    #!/bin/sh
    echo "{{ _cyan }}Running integration tests {{ _nc }}"
    uv run --with "pytest-xdist" pytest -{{ _test_verbosity }} --color=yes -n {{ _test_workers }} tests/integration/

[group('test')]
test-e2e: setup-test-env
    #!/bin/sh
    rm -rf .e2e/
    echo "{{ _cyan }}Running end-to-end tests {{ _nc }}"
    echo "Using SyftBox from {{ _green }}'$(which syftbox)'{{ _nc }}"
    uv run --with "pytest-xdist" pytest -{{ _test_verbosity }} --color=yes -n {{ _test_workers }} tests/e2e/

[group('test')]
test-notebooks: setup-test-env
    #!/bin/sh
    echo "{{ _cyan }}Running notebook tests {{ _nc }}"
    uv run --with "nbmake" \
        --with "pytest-xdist" pytest -{{ _test_verbosity }} \
        --color=yes -n {{ _test_workers }} \
        --nbmake notebooks/quickstart/full_flow.ipynb

[group('test')]
test: setup-test-env
    #!/bin/sh
    echo "{{ _cyan }}Running all tests in parallel{{ _nc }}"
    just test-unit &
    just test-integration &
    # just test-e2e &
    just test-notebooks &
    wait
    just clean

# ---------------------------------------------------------------------------------------------------------------------
# Bump version in pyproject.toml and __init__.py. Usage: just bump-version patch/minor/major
[group('build')]
bump version_type="patch":
    #!/bin/bash
    set -eou pipefail

    # Check if version_type is valid
    if [[ "{{ version_type }}" != "patch" && "{{ version_type }}" != "minor" && "{{ version_type }}" != "major" ]]; then
        echo "{{ _red }}Error: Invalid version type '{{ version_type }}'. Use: patch, minor, or major{{ _nc }}"
        exit 1
    fi

    # Get current version from pyproject.toml
    CURRENT_VERSION=$(grep '^version = ' pyproject.toml | sed 's/version = "\(.*\)"/\1/')

    # Parse version components
    IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"

    # Bump version based on type
    if [[ "{{ version_type }}" == "major" ]]; then
        NEW_MAJOR=$((MAJOR + 1))
        NEW_VERSION="${NEW_MAJOR}.0.0"
    elif [[ "{{ version_type }}" == "minor" ]]; then
        NEW_MINOR=$((MINOR + 1))
        NEW_VERSION="${MAJOR}.${NEW_MINOR}.0"
    else  # patch
        NEW_PATCH=$((PATCH + 1))
        NEW_VERSION="${MAJOR}.${MINOR}.${NEW_PATCH}"
    fi

    # Update version in pyproject.toml
    sed -i.bak "s/^version = \".*\"/version = \"$NEW_VERSION\"/" pyproject.toml && rm pyproject.toml.bak

    # Update version in __init__.py
    sed -i.bak "s/^__version__ = \".*\"/__version__ = \"$NEW_VERSION\"/" src/syft_rds/__init__.py && rm src/syft_rds/__init__.py.bak

    echo ""
    echo -e "{{ _green }}✓ Version bumped: $CURRENT_VERSION → $NEW_VERSION{{ _nc }}"
    echo ""
    echo -e "{{ _cyan }}Updated files:{{ _nc }}"
    echo "  • pyproject.toml"
    echo "  • src/syft_rds/__init__.py"
    echo ""
    echo -e "{{ _cyan }}Next steps:{{ _nc }}"
    echo "  0. just test"
    echo "  1. git add pyproject.toml src/syft_rds/__init__.py"
    echo "  2. git commit -m \"Bump version to $NEW_VERSION\""
    echo "  3. git tag v$NEW_VERSION"
    echo "  4. git push && git push --tags"
    echo "  5. just build"

# Build syft rds wheel
[group('build')]
build:
    @echo "{{ _cyan }}Building syft-rds wheel...{{ _nc }}"
    rm -rf dist/
    uv build
    @echo "{{ _green }}Build complete!{{ _nc }}"
    @echo "{{ _cyan }}To inspect the build:{{ _nc }}"
    @echo "{{ _cyan }}1. Go to the build directory and unzip the .tar.gz file to inspect the contents{{ _nc }}"
    @echo "{{ _cyan }}2. Inspect the .whl file with: uvx wheel unpack <path_to_whl_file>{{ _nc }}"
    @echo "{{ _cyan }}3. To upload to pypi, run: uvx twine upload ./dist/*{{ _nc }}"
# ---------------------------------------------------------------------------------------------------------------------

