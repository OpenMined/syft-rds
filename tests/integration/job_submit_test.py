import pytest

from tests.conftest import DS_PATH
from tests.utils import create_dataset

from syft_rds.client.exceptions import RDSValidationError
from syft_rds.client.rds_clients.runtime import (
    DEFAULT_RUNTIME_NAME,
    DEFAULT_DOCKERFILE_FILE_PATH,
)
from syft_rds.client.rds_client import RDSClient
from syft_rds.models import JobStatus


@pytest.mark.parametrize(
    "runtime_name, runtime_kind, runtime_config, submit_kwargs",
    [
        # Default runtime (python)
        (
            DEFAULT_RUNTIME_NAME,
            "python",
            None,
            {
                "name": "Test Job - Default Runtime",
                "description": "Job using default runtime",
                "user_code_path": f"{DS_PATH / 'code'}",
                "entrypoint": "main.py",
                "dataset_name": "dummy",
                "runtime_name": DEFAULT_RUNTIME_NAME,
            },
        ),
        # Python runtime with specific version
        (
            "python3.12",
            "python",
            {"version": "3.12"},
            {
                "name": "Test Job - Python 3.12",
                "description": "Job using Python 3.12 runtime",
                "user_code_path": f"{DS_PATH / 'code'}",
                "entrypoint": "main.py",
                "dataset_name": "dummy",
                "runtime_name": "python3.12",
            },
        ),
        # Docker runtime
        (
            "my_docker_python",
            "docker",
            {"dockerfile": str(DEFAULT_DOCKERFILE_FILE_PATH)},
            {
                "name": "Test Job - Docker",
                "description": "Job using Docker runtime",
                "user_code_path": f"{DS_PATH / 'code'}",
                "entrypoint": "main.py",
                "dataset_name": "dummy",
                "runtime_name": "my_docker_python",
            },
        ),
    ],
)
def test_job_submit_with_runtime(
    ds_rds_client: RDSClient,
    do_rds_client: RDSClient,
    runtime_name: str,
    runtime_kind: str,
    runtime_config: dict | None,
    submit_kwargs: dict,
):
    """Test that DS can submit jobs using runtimes created by DO."""
    # DO: create dataset
    create_dataset(do_rds_client, name=submit_kwargs["dataset_name"])

    # DO: create runtime
    created_runtime = do_rds_client.runtime.create(
        runtime_name=runtime_name,
        runtime_kind=runtime_kind,
        config=runtime_config,
        description=f"{runtime_kind} runtime for testing",
    )

    # DS: submit job (using runtime by name)
    job = ds_rds_client.job.submit(**submit_kwargs)

    assert job is not None
    assert job.status == JobStatus.pending_code_review
    assert job.runtime_id == created_runtime.uid

    # Verify runtime matches
    runtime = do_rds_client.runtime.get(uid=job.runtime_id)
    assert runtime.name == runtime_name
    assert runtime.kind == runtime_kind


def test_job_submit_nonexistent_runtime(
    ds_rds_client: RDSClient,
    do_rds_client: RDSClient,
):
    """Test that DS cannot submit job with non-existent runtime."""
    # DO: create dataset
    create_dataset(do_rds_client, name="test_dataset")

    # DS: try to submit job with non-existent runtime
    with pytest.raises(
        RDSValidationError,
        match="Runtime 'nonexistent_runtime' does not exist",
    ):
        ds_rds_client.job.submit(
            name="Test Job",
            user_code_path=DS_PATH / "code",
            entrypoint="main.py",
            dataset_name="test_dataset",
            runtime_name="nonexistent_runtime",
        )


def test_ds_cannot_create_runtime(ds_rds_client: RDSClient):
    """Test that DS cannot create runtimes (only DO can)."""
    with pytest.raises(PermissionError, match="must be the datasite admin"):
        ds_rds_client.runtime.create(
            runtime_name="unauthorized_runtime",
            runtime_kind="python",
        )


def test_job_submit_without_runtime(
    ds_rds_client: RDSClient,
    do_rds_client: RDSClient,
):
    """Test that jobs can run without specifying a runtime."""
    # DO: create dataset
    create_dataset(do_rds_client, name="test_dataset")

    # DS: submit job without runtime
    job = ds_rds_client.job.submit(
        name="No Runtime Job",
        user_code_path=DS_PATH / "code",
        entrypoint="main.py",
        dataset_name="test_dataset",
        # No runtime_name specified
    )

    assert job is not None
    assert job.status == JobStatus.pending_code_review
    assert job.runtime_id is None


def test_job_submit_with_ignore_patterns(
    ds_rds_client: RDSClient,
    do_rds_client: RDSClient,
    tmp_path,
):
    """Test that ignore patterns work when submitting jobs."""
    # DO: create dataset
    create_dataset(do_rds_client, name="test_dataset")

    # DS: create code directory with files that should be ignored
    code_dir = tmp_path / "test_code"
    code_dir.mkdir()

    # Create main entrypoint
    (code_dir / "main.py").write_text("print('Hello from main')")
    (code_dir / "utils.py").write_text("def helper(): pass")

    # Create files that should be ignored by default
    (code_dir / ".venv").mkdir()
    (code_dir / ".venv" / "lib.py").write_text("# venv file")

    (code_dir / "__pycache__").mkdir()
    (code_dir / "__pycache__" / "main.pyc").write_text("# compiled")

    (code_dir / "test.pyc").write_text("# compiled file")
    (code_dir / ".DS_Store").write_text("# mac file")

    # DS: submit job with default ignore patterns (should ignore .venv, __pycache__, etc.)
    job = ds_rds_client.job.submit(
        name="Job with Ignore Patterns",
        user_code_path=code_dir,
        entrypoint="main.py",
        dataset_name="test_dataset",
    )

    assert job is not None
    assert job.status == JobStatus.pending_code_review

    # Verify that the uploaded code doesn't contain ignored files
    user_code = ds_rds_client.user_code.get(uid=job.user_code_id, mode="local")

    # Check the extracted files in local_dir
    local_dir = user_code.local_dir
    all_files = [f.relative_to(local_dir) for f in local_dir.rglob("*") if f.is_file()]
    all_files_str = [str(f) for f in all_files]

    # Should include source files
    assert any(
        "main.py" in f for f in all_files_str
    ), f"main.py not found in {all_files_str}"
    assert any(
        "utils.py" in f for f in all_files_str
    ), f"utils.py not found in {all_files_str}"

    # Should NOT include ignored files
    assert not any(
        ".venv" in f for f in all_files_str
    ), f"Found .venv in {all_files_str}"
    assert not any(
        "__pycache__" in f for f in all_files_str
    ), f"Found __pycache__ in {all_files_str}"
    assert not any(
        f.endswith(".pyc") for f in all_files_str
    ), f"Found .pyc files in {all_files_str}"
    assert not any(
        ".DS_Store" in f for f in all_files_str
    ), f"Found .DS_Store in {all_files_str}"


def test_job_submit_with_custom_ignore_patterns(
    ds_rds_client: RDSClient,
    do_rds_client: RDSClient,
    tmp_path,
):
    """Test submitting jobs with custom ignore patterns."""
    # DO: create dataset
    create_dataset(do_rds_client, name="test_dataset")

    # DS: create code directory
    code_dir = tmp_path / "custom_ignore_code"
    code_dir.mkdir()

    (code_dir / "main.py").write_text("print('Main')")
    (code_dir / "config.json").write_text("{}")
    (code_dir / "secret.key").write_text("secret")
    (code_dir / "data.csv").write_text("a,b,c")

    # Submit with custom ignore patterns: only ignore .key and .csv files
    job = ds_rds_client.job.submit(
        name="Custom Ignore Job",
        user_code_path=code_dir,
        entrypoint="main.py",
        dataset_name="test_dataset",
        ignore_patterns=["*.key", "*.csv"],
    )

    assert job is not None

    # Verify uploaded files
    user_code = ds_rds_client.user_code.get(uid=job.user_code_id, mode="local")
    local_dir = user_code.local_dir
    all_files = [f.relative_to(local_dir) for f in local_dir.rglob("*") if f.is_file()]
    all_files_str = [str(f) for f in all_files]

    # Should include
    assert any("main.py" in f for f in all_files_str)
    assert any("config.json" in f for f in all_files_str)

    # Should NOT include (custom ignores)
    assert not any("secret.key" in f for f in all_files_str)
    assert not any("data.csv" in f for f in all_files_str)


def test_job_submit_with_no_ignore_patterns(
    ds_rds_client: RDSClient,
    do_rds_client: RDSClient,
    tmp_path,
):
    """Test submitting jobs with ignore_patterns=[] to include all files."""
    # DO: create dataset
    create_dataset(do_rds_client, name="test_dataset")

    # DS: create code directory with normally-ignored files
    code_dir = tmp_path / "no_ignore_code"
    code_dir.mkdir()

    (code_dir / "main.py").write_text("print('Main')")
    (code_dir / ".venv").mkdir()
    (code_dir / ".venv" / "lib.py").write_text("# venv")
    (code_dir / "test.pyc").write_text("# compiled")

    # Submit with empty ignore list = include everything
    job = ds_rds_client.job.submit(
        name="No Ignore Job",
        user_code_path=code_dir,
        entrypoint="main.py",
        dataset_name="test_dataset",
        ignore_patterns=[],  # Empty list = ignore nothing
    )

    assert job is not None

    # Verify all files are included
    user_code = ds_rds_client.user_code.get(uid=job.user_code_id, mode="local")
    local_dir = user_code.local_dir
    all_files = [f.relative_to(local_dir) for f in local_dir.rglob("*") if f.is_file()]
    all_files_str = [str(f) for f in all_files]

    # Everything should be included
    assert any("main.py" in f for f in all_files_str)
    assert any(".venv" in f and "lib.py" in f for f in all_files_str)
    assert any("test.pyc" in f for f in all_files_str)
