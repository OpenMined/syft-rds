"""Integration tests for UV runtime support."""

import time

import pytest

from syft_rds.client.rds_client import RDSClient
from syft_rds.models import JobStatus
from syft_rds.utils.constants import JOB_STATUS_POLLING_INTERVAL
from tests.conftest import DS_PATH
from tests.utils import create_dataset


def test_uv_runtime_with_pyproject_toml(
    ds_rds_client: RDSClient,
    do_rds_client: RDSClient,
):
    """Test that jobs with pyproject.toml use UV for dependency installation."""
    # DO: create dataset
    create_dataset(do_rds_client, "dummy")

    # DO: create Python runtime with use_uv=True (default)
    runtime = do_rds_client.runtime.create(
        runtime_name="test_uv_runtime",
        runtime_kind="python",
        config={"use_uv": True},
    )
    assert runtime.config.use_uv is True

    # DS: submit job with code that has pyproject.toml
    code_with_deps = DS_PATH / "code_with_deps"
    assert (
        code_with_deps / "pyproject.toml"
    ).exists(), "Test asset pyproject.toml not found"

    job = ds_rds_client.job.submit(
        user_code_path=code_with_deps,
        dataset_name="dummy",
        entrypoint="main.py",
        runtime_name="test_uv_runtime",
    )
    assert job.status == JobStatus.pending_code_review
    assert job.runtime_id == runtime.uid

    # DO: approve and run job
    approved_job = do_rds_client.job.approve(job)
    assert approved_job.status == JobStatus.approved

    do_rds_client.run_private(approved_job, blocking=True)

    # Verify job succeeded (dependencies were installed via UV)
    job = do_rds_client.job.get(uid=job.uid)
    assert (
        job.status == JobStatus.job_run_finished
    ), f"Job failed with error: {job.error_message}"

    # Verify output was created correctly
    do_rds_client.job.share_results(job)
    job = do_rds_client.job.get(uid=job.uid)
    assert job.status == JobStatus.shared

    output_file = job.output_path / "output" / "result.txt"
    assert output_file.exists()

    # Verify the output content
    content = output_file.read_text()
    assert "UV dependency test passed!" in content


def test_uv_runtime_without_pyproject_toml(
    ds_rds_client: RDSClient,
    do_rds_client: RDSClient,
):
    """Test that jobs without pyproject.toml fall back to standard Python execution."""
    # DO: create dataset
    create_dataset(do_rds_client, "dummy")

    # DO: create Python runtime with use_uv=True
    do_rds_client.runtime.create(
        runtime_name="test_uv_fallback",
        runtime_kind="python",
        config={"use_uv": True},
    )

    # DS: submit job with code that does NOT have pyproject.toml
    code_without_deps = DS_PATH / "code"
    assert not (code_without_deps / "pyproject.toml").exists()

    job = ds_rds_client.job.submit(
        user_code_path=code_without_deps / "main.py",
        dataset_name="dummy",
        runtime_name="test_uv_fallback",
    )

    # DO: approve and run job
    approved_job = do_rds_client.job.approve(job)
    do_rds_client.run_private(approved_job, blocking=True)

    # Verify job succeeded with standard Python execution
    job = do_rds_client.job.get(uid=job.uid)
    assert job.status == JobStatus.job_run_finished


def test_uv_disabled_runtime(
    ds_rds_client: RDSClient,
    do_rds_client: RDSClient,
):
    """Test that use_uv=False disables UV even when pyproject.toml exists."""
    # DO: create dataset
    create_dataset(do_rds_client, "dummy")

    # DO: create Python runtime with use_uv=False
    runtime = do_rds_client.runtime.create(
        runtime_name="test_uv_disabled",
        runtime_kind="python",
        config={"use_uv": False},
    )
    assert runtime.config.use_uv is False

    # DS: submit job with code that has pyproject.toml
    code_with_deps = DS_PATH / "code_with_deps"

    job = ds_rds_client.job.submit(
        user_code_path=code_with_deps,
        dataset_name="dummy",
        entrypoint="main.py",
        runtime_name="test_uv_disabled",
    )

    # DO: approve and run job
    approved_job = do_rds_client.job.approve(job)
    do_rds_client.run_private(approved_job, blocking=True)

    # Verify job failed (dependencies not installed because UV is disabled)
    job = do_rds_client.job.get(uid=job.uid)
    assert job.status == JobStatus.job_run_failed
    assert (
        "ModuleNotFoundError" in job.error_message
        or "No module named" in job.error_message
    )


def test_default_runtime_uses_uv(
    ds_rds_client: RDSClient,
    do_rds_client: RDSClient,
):
    """Test that jobs without explicit runtime default to use_uv=True."""
    # DO: create dataset
    create_dataset(do_rds_client, "dummy")

    # DS: submit job without specifying runtime (uses default)
    code_with_deps = DS_PATH / "code_with_deps"

    job = ds_rds_client.job.submit(
        user_code_path=code_with_deps,
        dataset_name="dummy",
        entrypoint="main.py",
        # No runtime_name specified - should use default with use_uv=True
    )

    assert job.runtime_id is None  # No runtime created

    # DO: approve and run job
    approved_job = do_rds_client.job.approve(job)
    do_rds_client.run_private(approved_job, blocking=True)

    # Verify job succeeded with ephemeral UV runtime
    job = do_rds_client.job.get(uid=job.uid)
    assert job.status == JobStatus.job_run_finished


def test_uv_runtime_nonblocking(
    ds_rds_client: RDSClient,
    do_rds_client: RDSClient,
):
    """Test UV runtime in non-blocking mode."""
    # DO: create dataset
    create_dataset(do_rds_client, "dummy")

    # DO: create Python runtime with use_uv=True
    do_rds_client.runtime.create(
        runtime_name="test_uv_nonblocking",
        runtime_kind="python",
        config={"use_uv": True},
    )

    # DS: submit job
    code_with_deps = DS_PATH / "code_with_deps"
    job = ds_rds_client.job.submit(
        user_code_path=code_with_deps,
        dataset_name="dummy",
        entrypoint="main.py",
        runtime_name="test_uv_nonblocking",
    )

    # DO: approve and run job in non-blocking mode
    approved_job = do_rds_client.job.approve(job)
    do_rds_client.run_private(approved_job, blocking=False)

    # Poll until job finishes
    max_wait = 30  # UV might take longer on first run
    elapsed = 0
    while elapsed < max_wait:
        job = do_rds_client.job.get(uid=job.uid)
        if job.status == JobStatus.job_run_finished:
            break
        time.sleep(JOB_STATUS_POLLING_INTERVAL)
        elapsed += JOB_STATUS_POLLING_INTERVAL

    # Verify job succeeded
    job = do_rds_client.job.get(uid=job.uid)
    assert job.status == JobStatus.job_run_finished


def test_get_logs(
    ds_rds_client: RDSClient,
    do_rds_client: RDSClient,
):
    """Test the get_logs() method for retrieving job logs."""
    # DO: create dataset
    create_dataset(do_rds_client, "dummy")

    # DS: submit and run job with colorama output
    code_with_deps = DS_PATH / "code_with_deps"
    job = ds_rds_client.job.submit(
        user_code_path=code_with_deps,
        dataset_name="dummy",
        entrypoint="main.py",
    )

    # DO: approve and run job
    approved_job = do_rds_client.job.approve(job)
    do_rds_client.run_private(approved_job, blocking=True)

    # Verify job succeeded
    job = do_rds_client.job.get(uid=job.uid)
    assert job.status == JobStatus.job_run_finished

    # Test get_logs() method
    logs = do_rds_client.job.get_logs(job)

    # Verify logs structure
    assert isinstance(logs, dict)
    assert "stdout" in logs
    assert "stderr" in logs

    # Verify stdout contains our print statements
    stdout_content = logs["stdout"]
    assert len(stdout_content) > 0, "stdout should not be empty"
    assert "UV Dependency Installation Test" in stdout_content
    assert "colorama dependency was installed by UV" in stdout_content
    assert "UV runtime working correctly" in stdout_content

    # Test get_logs() with UID
    logs_by_uid = do_rds_client.job.get_logs(job.uid)
    assert logs_by_uid == logs


def test_get_logs_before_execution(
    ds_rds_client: RDSClient,
    do_rds_client: RDSClient,
):
    """Test that get_logs() raises error for jobs that haven't been executed."""
    # DO: create dataset
    create_dataset(do_rds_client, "dummy")

    # DS: submit job but don't run it
    code_path = DS_PATH / "code" / "main.py"
    job = ds_rds_client.job.submit(
        user_code_path=code_path,
        dataset_name="dummy",
    )

    # Try to get logs before execution
    with pytest.raises(ValueError, match="Logs directory does not exist"):
        do_rds_client.job.get_logs(job)
