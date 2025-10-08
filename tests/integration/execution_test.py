import time

import pytest
import pandas as pd

from syft_rds.client.rds_client import RDSClient
from syft_rds.client.rds_clients.runtime import (
    DEFAULT_DOCKERFILE_FILE_PATH,
)
from syft_rds.models import Job, JobStatus
from syft_rds.utils.constants import JOB_STATUS_POLLING_INTERVAL
from tests.conftest import DS_PATH
from tests.utils import create_dataset

single_file_submission = {"user_code_path": DS_PATH / "code" / "main.py"}
folder_submission = {"user_code_path": DS_PATH / "code", "entrypoint": "main.py"}

# Test cases: DO creates runtimes, DS uses them by name
runtime_configs = {
    "default_runtime": {
        "do_creates_runtime": False,  # No runtime needed
        "ds_submit_params": {},  # No runtime_name = runtime_id will be None
    },
    "python_runtime": {
        "do_creates_runtime": True,
        "runtime_create_params": {
            "runtime_name": "test_python",
            "runtime_kind": "python",
        },
        "ds_submit_params": {"runtime_name": "test_python"},
    },
    "docker_runtime": {
        "do_creates_runtime": True,
        "runtime_create_params": {
            "runtime_name": "test_docker",
            "runtime_kind": "docker",
            "config": {"dockerfile": str(DEFAULT_DOCKERFILE_FILE_PATH)},
        },
        "ds_submit_params": {"runtime_name": "test_docker"},
    },
}

test_cases = []
for sub_type, sub_params in [
    ("single_file", single_file_submission),
    ("folder", folder_submission),
]:
    for rt_name, rt_config in runtime_configs.items():
        for blocking_mode in [True, False]:
            blocking_str = "blocking" if blocking_mode else "non_blocking"
            test_cases.append(
                {
                    "id": f"{sub_type}_{rt_name}_{blocking_str}",
                    "submission_params": {
                        **sub_params,
                        **rt_config["ds_submit_params"],
                    },
                    "runtime_config": rt_config,
                    "blocking": blocking_mode,
                }
            )


@pytest.mark.parametrize(
    "test_case",
    test_cases,
    ids=lambda x: x["id"],
)
def test_job_execution(
    ds_rds_client: RDSClient,
    do_rds_client: RDSClient,
    test_case: dict,
):
    """Test job execution with a file or a folder, for various configurations."""
    blocking_mode = test_case["blocking"]
    runtime_config = test_case["runtime_config"]

    # DO: create dataset
    create_dataset(do_rds_client, "dummy")

    # DO: create runtime if needed
    if runtime_config["do_creates_runtime"]:
        do_rds_client.runtime.create(**runtime_config["runtime_create_params"])

    # DS: submit job
    submit_kwargs = {
        "dataset_name": "dummy",
        **test_case["submission_params"],
    }
    job = ds_rds_client.job.submit(**submit_kwargs)
    assert job.status == JobStatus.pending_code_review

    # Verify runtime was created/used correctly
    all_runtimes = do_rds_client.runtime.get_all()
    if runtime_config["do_creates_runtime"]:
        assert len(all_runtimes) == 1
        assert job.runtime_id == all_runtimes[0].uid
    else:
        # Default runtime case - no runtime created
        assert job.runtime_id is None

    # DO reviews, runs, and shares job
    _run_and_verify_job(do_rds_client, blocking=blocking_mode)


def _run_and_verify_job(do_rds_client: RDSClient, blocking: bool):
    """Helper function to run a job and verify its execution."""
    job: Job = do_rds_client.job.get_all()[0]

    # DO approves the job
    approved_job = do_rds_client.job.approve(job)
    assert approved_job.status == JobStatus.approved

    # DO runs the job
    do_rds_client.run_private(approved_job, blocking=blocking)

    if not blocking:
        # Poll until job finishes
        max_wait = 10  # seconds
        elapsed = 0
        while elapsed < max_wait:
            job = do_rds_client.job.get(uid=job.uid)
            if job.status == JobStatus.job_run_finished:
                break
            time.sleep(JOB_STATUS_POLLING_INTERVAL)
            elapsed += JOB_STATUS_POLLING_INTERVAL

    job = do_rds_client.job.get(uid=job.uid)
    assert job.status == JobStatus.job_run_finished

    # DO shares the results
    do_rds_client.job.share_results(job)
    job = do_rds_client.job.get(uid=job.uid)
    assert job.status == JobStatus.shared

    # Verify job output
    output_path = job.output_path
    assert output_path.exists()

    output_file = output_path / "output" / "result.csv"
    assert output_file.exists()

    # Verify the output has correct computation
    df = pd.read_csv(output_file)
    assert "sum" in df.columns
    assert len(df) == 5  # 5 rows of data
    # Verify first row: A=2, B=3, C=4, sum should be 9
    assert df.iloc[0]["sum"] == 9
