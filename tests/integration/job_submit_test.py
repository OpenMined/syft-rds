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
