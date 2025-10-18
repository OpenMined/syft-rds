import enum
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

from IPython.display import HTML, display
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, model_validator
from syft_core import SyftBoxURL

from syft_rds.display_utils.html_format import create_html_repr
from syft_rds.models.base import ItemBase, ItemBaseCreate, ItemBaseUpdate
from syft_rds.models.runtime_models import Runtime
from syft_rds.utils.name_generator import generate_name

if TYPE_CHECKING:
    from syft_rds.models import CustomFunction, UserCode


class JobStatus(str, enum.Enum):
    pending_code_review = "pending_code_review"
    job_run_failed = "job_run_failed"
    job_run_finished = "job_run_finished"
    job_in_progress = "job_in_progress"

    # end states
    rejected = "rejected"  # failed to pass the review
    shared = "shared"  # shared with the user
    approved = "approved"  # approved by the reviewer


class JobErrorKind(str, enum.Enum):
    no_error = "no_error"
    timeout = "timeout"
    cancelled = "cancelled"
    execution_failed = "execution_failed"
    failed_code_review = "failed_code_review"
    failed_output_review = "failed_output_review"


class Job(ItemBase):
    model_config = ConfigDict(extra="forbid")

    __schema_name__ = "job"
    __table_extra_fields__ = [
        "created_by",
        "name",
        "dataset_name",
        "runtime_name",
        "status",
        "error",
        "error_message",
    ]

    name: str = Field(default_factory=generate_name)
    dataset_name: Optional[str] = None
    user_code_id: UUID

    runtime_id: Optional[UUID] = None
    custom_function_id: Optional[UUID] = None
    enclave: str = ""

    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    user_metadata: dict = {}

    status: JobStatus = JobStatus.pending_code_review
    error: JobErrorKind = JobErrorKind.no_error
    error_message: str | None = None
    output_url: SyftBoxURL | None = None

    def describe(self) -> None:
        fields = [
            "uid",
            "created_by",
            "created_at",
            "updated_at",
            "name",
            "description",
            "status",
            "error",
            "error_message",
            "output_path",
            "dataset_name",
            "user_code_name",
        ]

        # Conditionally add optional fields
        if self.runtime_id is not None:
            fields.append("runtime_name")
        if self.custom_function_id is not None:
            fields.append("custom_function_name")
        if self.enclave:
            fields.append("enclave")

        html_description = create_html_repr(
            obj=self,
            fields=fields,
            display_paths=["output_path"],
        )
        display(HTML(html_description))

    @property
    def runtime(self) -> Optional["Runtime"]:
        """Get the runtime of the job"""
        if self.runtime_id is None:
            return None
        return self._client.runtime.get(self.runtime_id)

    @property
    def runtime_name(self) -> Optional[str]:
        """Get the name of the runtime of the job"""
        runtime = self.runtime
        return runtime.name if runtime else None

    @property
    def user_code(self) -> "UserCode":
        return self._client.user_code.get(self.user_code_id)

    @property
    def user_code_name(self) -> str:
        return self.user_code.name

    @property
    def custom_function(self) -> "Optional[CustomFunction]":
        if self.custom_function_id is None:
            return None
        client = self._client
        return client.custom_function.get(self.custom_function_id)

    @property
    def custom_function_name(self) -> Optional[str]:
        if self.custom_function is None:
            return None
        return self.custom_function.name

    def show_user_code(self) -> None:
        user_code = self.user_code
        user_code.describe()

    def get_update_for_reject(self, reason: str = "unknown reason") -> "JobUpdate":
        """
        Create a JobUpdate object with the rejected status
        based on the current status
        """
        allowed_statuses = (
            JobStatus.pending_code_review,
            JobStatus.job_run_finished,
            JobStatus.job_run_failed,
        )
        if self.status not in allowed_statuses:
            raise ValueError(f"Cannot reject job with status: {self.status}")

        original_status = self.status
        self.error_message = reason
        self.status = JobStatus.rejected
        self.error = (
            JobErrorKind.failed_code_review
            if original_status == JobStatus.pending_code_review
            else JobErrorKind.failed_output_review
        )
        return JobUpdate(
            uid=self.uid,
            status=self.status,
            error=self.error,
            error_message=self.error_message,
        )

    def get_update_for_approve(self) -> "JobUpdate":
        """
        Create a JobUpdate object with the approved status
        based on the current status
        """
        allowed_statuses = (JobStatus.pending_code_review,)
        if self.status not in allowed_statuses:
            raise ValueError(f"Cannot approve job with status: {self.status}")

        self.status = JobStatus.approved

        return JobUpdate(
            uid=self.uid,
            status=self.status,
        )

    def get_update_for_in_progress(self) -> "JobUpdate":
        return JobUpdate(
            uid=self.uid,
            status=JobStatus.job_in_progress,
        )

    def get_update_for_return_code(
        self, return_code: int | subprocess.Popen, error_message: str | None = None
    ) -> "JobUpdate":
        if not isinstance(return_code, int):
            return self.get_update_for_in_progress()
        if return_code == 0:
            self.status = JobStatus.job_run_finished
            self.error = JobErrorKind.no_error
            self.error_message = None
        else:
            self.status = JobStatus.job_run_failed
            self.error = JobErrorKind.execution_failed
            self.error_message = error_message

        return JobUpdate(
            uid=self.uid,
            status=self.status,
            error=self.error,
            error_message=self.error_message,
        )

    @property
    def output_path(self) -> Path:
        """Path to shared job output (after job.share_results())."""
        return self.get_output_path()

    def get_output_path(self) -> Path:
        if self.output_url is None:
            raise ValueError("output_url is not set")
        client = self._client
        return self.output_url.to_local_path(
            datasites_path=client._syftbox_client.datasites
        )

    @model_validator(mode="after")
    def validate_status(self):
        if (
            self.status == JobStatus.job_run_failed
            and self.error == JobErrorKind.no_error
        ):
            raise ValueError("error must be set if status is failed")
        return self


class JobUpdate(ItemBaseUpdate[Job]):
    status: Optional[JobStatus] = None
    error: Optional[JobErrorKind] = None
    error_message: Optional[str] = None


class JobCreate(ItemBaseCreate[Job]):
    dataset_name: Optional[str] = None
    user_code_id: UUID
    runtime_id: Optional[UUID] = None
    name: Optional[str] = None
    description: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    custom_function_id: Optional[UUID] = None
    enclave: str = ""


class JobConfig(BaseModel):
    """Configuration for a job run"""

    function_folder: Path
    args: list[str]
    uv_args: list[str] = []  # Arguments for 'uv run' command (e.g., --active, --frozen)
    data_path: Optional[Path] = None  # None for jobs that don't need pre-existing data
    runtime: "Runtime"
    job_folder: Optional[Path] = Field(
        default_factory=lambda: Path("jobs") / datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    timeout: int = 60
    data_mount_dir: str = "/app/data"
    extra_env: dict[str, str] = {}
    blocking: bool = Field(default=True)

    def model_post_init(self, __context: Any) -> None:
        """Ensure all paths are absolute for consistency and safety"""
        # Convert to absolute paths
        self.function_folder = self.function_folder.absolute()
        if self.data_path is not None:
            self.data_path = self.data_path.absolute()
        if self.job_folder is not None:
            self.job_folder = self.job_folder.absolute()

    @property
    def job_path(self) -> Path:
        """Derived path for job folder"""
        return Path(self.job_folder)

    @property
    def logs_dir(self) -> Path:
        """Derived path for logs directory"""
        return self.job_path / "logs"

    @property
    def output_dir(self) -> Path:
        """Derived path for output directory"""
        return self.job_path / "output"

    def get_env(self) -> dict[str, str]:
        return self.extra_env | self._base_env

    def get_env_as_docker_args(self) -> list[str]:
        return [f"-e {k}={v}" for k, v in self.get_env().items()]

    def get_extra_env_as_docker_args(self) -> list[str]:
        return [f"-e {k}={v}" for k, v in self.extra_env.items()]

    @property
    def _base_env(self) -> dict[str, str]:
        interpreter = " ".join(self.runtime.cmd)
        # interpreter_str = f"'{interpreter}'" if " " in interpreter else interpreter
        env = {
            "OUTPUT_DIR": str(self.output_dir.absolute()),
            "CODE_DIR": str(self.function_folder.absolute()),
            "TIMEOUT": str(self.timeout),
            "INPUT_FILE": str(self.function_folder / self.args[0]),
            "INTERPRETER": interpreter,
        }
        # Only set DATA_DIR if data_path exists
        if self.data_path is not None:
            env["DATA_DIR"] = str(self.data_path.absolute())
        return env


class JobResults(BaseModel):
    _MAX_LOADED_FILE_SIZE: int = 10 * 1024 * 1024  # 10 MB

    job: Job
    results_dir: Path

    @property
    def logs_dir(self) -> Path:
        return self.results_dir / "logs"

    @property
    def output_dir(self) -> Path:
        return self.results_dir / "output"

    @property
    def stderr_file(self) -> Path:
        return self.logs_dir / "stderr.log"

    @property
    def stdout_file(self) -> Path:
        return self.logs_dir / "stdout.log"

    @property
    def stderr(self) -> str | None:
        if self.stderr_file.exists():
            return self.stderr_file.read_text(errors="replace")
        return None

    @property
    def stdout(self) -> str | None:
        if self.stdout_file.exists():
            return self.stdout_file.read_text(errors="replace")
        return None

    @property
    def log_files(self) -> list[Path]:
        return list(self.logs_dir.glob("*"))

    @property
    def output_files(self) -> list[Path]:
        return list(self.output_dir.glob("*"))

    @property
    def outputs(self) -> dict[str, Any]:
        outputs = {}
        for file in self.output_dir.glob("*"):
            try:
                contents = load_output_file(
                    filepath=file, max_size=self._MAX_LOADED_FILE_SIZE
                )
                outputs[file.name] = contents
            except ValueError as e:
                logger.warning(
                    f"Skipping output {file.name}: {e}. Please load this file manually."
                )
                continue
        return outputs

    def describe(self):
        display_paths = ["output_dir"]
        if self.stdout_file.exists():
            display_paths.append("stdout_file")
        if self.stderr_file.exists():
            display_paths.append("stderr_file")

        html_repr = create_html_repr(
            obj=self,
            fields=["output_dir", "logs_dir"],
            display_paths=display_paths,
        )

        display(HTML(html_repr))


def load_output_file(filepath: Path, max_size: int) -> Any:
    if not filepath.exists():
        raise ValueError(f"File {filepath} does not exist.")

    file_size = filepath.stat().st_size
    if file_size > max_size:
        raise ValueError(
            f"File the maximum size of {int(max_size / (1024 * 1024))} MB."
        )

    if filepath.suffix == ".json":
        with open(filepath, "r") as f:
            return json.load(f)

    elif filepath.suffix == ".parquet":
        import pandas as pd

        return pd.read_parquet(filepath)

    elif filepath.suffix == ".csv":
        import pandas as pd

        return pd.read_csv(filepath)

    elif filepath.suffix in {".txt", ".log", ".md", ".html"}:
        with open(filepath, "r", errors="replace") as f:
            return f.read()

    else:
        raise ValueError("Unsupported file type.")
