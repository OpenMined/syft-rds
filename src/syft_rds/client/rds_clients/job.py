import json
import shutil
import tempfile
from pathlib import Path
from typing_extensions import Any, Optional, Union
from uuid import UUID
import html

from loguru import logger

from syft_core import Client
from syft_rds.client.exceptions import RDSValidationError
from syft_rds.client.rds_clients.base import RDSClientModule
from syft_rds.client.utils import PathLike
from syft_rds.models import (
    Job,
    JobCreate,
    JobStatus,
    JobUpdate,
    UserCode,
)
from syft_rds.models.custom_function_models import CustomFunction
from syft_rds.models.job_models import JobErrorKind, JobResults


class JobRDSClient(RDSClientModule[Job]):
    ITEM_TYPE = Job

    def submit(
        self,
        user_code_path: PathLike,
        dataset_name: Optional[str] = None,
        entrypoint: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[list[str]] = None,
        custom_function: Optional[Union[CustomFunction, UUID]] = None,
        runtime_name: Optional[str] = None,
        enclave: str = "",
        ignore_patterns: Optional[list[str]] = None,
    ) -> Job:
        """`submit` is a convenience method to create both a UserCode and a Job in one call.

        Note: If the Data Owner's server is offline when you submit, this method will
        timeout after 5 minutes (default RPC timeout). However, your request is persisted
        to disk and will be automatically processed when the Data Owner's server comes
        online. You can check later with `client.job.get_all()` to see if your job was created.

        Args:
            user_code_path: Path to the code file or directory
            dataset_name: Name of the dataset to use (optional)
            entrypoint: Entry point file for folder-type code
            name: Optional name for the job
            description: Optional description for the job
            tags: Optional tags for the job
            custom_function: Optional CustomFunction or UUID to use
            runtime_name: Optional runtime name to use
            enclave: Optional enclave to use
            ignore_patterns: Optional list of patterns to ignore when uploading code.
                        If None, uses default ignore patterns (.venv, __pycache__, etc.).
                        Pass [] to include all files.

        Returns:
            Job: The created job

        Raises:
            SyftTimeoutError: If Data Owner's server doesn't respond within the timeout period
                            (default 5 minutes). Your request is still saved and will be
                            processed when the server comes online.
        """
        if custom_function is not None:
            custom_function_id = self._resolve_custom_func_id(custom_function)
            custom_function = (
                self.rds.custom_function.get(uid=custom_function_id)
                if custom_function_id
                else None
            )
            if entrypoint is not None:
                raise RDSValidationError(
                    "Cannot specify entrypoint when using a custom function."
                )
            entrypoint = custom_function.entrypoint

        user_code = self.rds.user_code.create(
            code_path=user_code_path,
            entrypoint=entrypoint,
            ignore_patterns=ignore_patterns,
        )

        if runtime_name is not None:
            try:
                self.rds.runtime.get(name=runtime_name)
            except ValueError:
                available_runtimes = self.rds.runtime.get_all()
                available_names = [r.name for r in available_runtimes]
                raise RDSValidationError(
                    f"Runtime '{runtime_name}' does not exist on {self.rds.host}. "
                    f"Available runtimes: {available_names}. "
                    f"Ask the data owner to create the runtime first."
                )

        job = self.create(
            name=name,
            description=description,
            user_code=user_code,
            dataset_name=dataset_name,
            tags=tags,
            custom_function=custom_function,
            runtime_name=runtime_name,
            enclave=enclave,
        )

        return job

    def submit_with_params(
        self,
        dataset_name: Optional[str],
        custom_function: Union[CustomFunction, UUID],
        ignore_patterns: Optional[list[str]] = None,
        **params: Any,
    ) -> Job:
        """
        Utility method to submit a job with parameters for a custom function.

        Args:
            dataset_name (str): The name of the dataset to use.
            custom_function (Union[CustomFunction, UUID]): The custom function to use.
            ignore_patterns: Optional list of patterns to ignore when uploading code.
                        If None, uses default ignore patterns (.venv, __pycache__, etc.).
            **params: Additional parameters to pass to the custom function.

        Returns:
            Job: The created job.
        """
        if isinstance(custom_function, UUID):
            custom_function = self.rds.custom_function.get(uid=custom_function)
        elif not isinstance(custom_function, CustomFunction):
            raise ValueError(
                f"Invalid custom_function type {type(custom_function)}. Must be CustomFunction or UUID"
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_dir_path = Path(tmpdir)
            user_params_path = tmp_dir_path / custom_function.input_params_filename
            if not user_params_path.suffix == ".json":
                raise ValueError(
                    f"Input params file must be a JSON file, got {user_params_path.suffix}. Please contact the administrator."
                )

            try:
                params_json = json.dumps(params)
            except Exception as e:
                raise ValueError(f"Failed to serialize params to JSON: {e}.") from e

            user_params_path.write_text(params_json)

            return self.submit(
                user_code_path=user_params_path,
                dataset_name=dataset_name,
                custom_function=custom_function,
                ignore_patterns=ignore_patterns,
            )

    def _resolve_custom_func_id(
        self, custom_function: Optional[Union[CustomFunction, UUID]]
    ) -> Optional[UUID]:
        if custom_function is None:
            return None
        if isinstance(custom_function, UUID):
            return custom_function
        elif isinstance(custom_function, CustomFunction):
            return custom_function.uid
        else:
            raise RDSValidationError(
                f"Invalid custom_function type {type(custom_function)}. Must be CustomFunction, UUID, or None"
            )

    def _resolve_usercode_id(self, user_code: Union[UserCode, UUID]) -> UUID:
        if isinstance(user_code, UUID):
            return user_code
        elif isinstance(user_code, UserCode):
            return user_code.uid
        else:
            raise RDSValidationError(
                f"Invalid user_code type {type(user_code)}. Must be UserCode, UUID, or str"
            )

    def _resolve_runtime_id(self, runtime_name: Optional[str]) -> Optional[UUID]:
        if runtime_name is None:
            return None
        runtime = self.rds.runtime.get(name=runtime_name)
        if not runtime:
            available_runtimes = self.rds.runtime.get_all()
            available_names = [r.name for r in available_runtimes]
            raise RDSValidationError(
                f"Runtime '{runtime_name}' does not exist on {self.rds.host}. "
                f"Available runtimes: {available_names}. "
                f"Ask the data owner to create the runtime first."
            )
        return runtime.uid

    def _verify_enclave(self, enclave: str) -> None:
        """Verify that the enclave is valid."""
        client: Client = self.rpc.connection.sender_client
        enclave_app_dir = client.app_data("enclave", datasite=enclave)
        public_key_path = enclave_app_dir / "keys" / "public_key.pem"
        if not public_key_path.exists():
            raise RDSValidationError(
                f"Enclave {enclave} does not exist or is not valid. "
                f"Public key file {public_key_path} not found."
            )

    def create(
        self,
        user_code: Union[UserCode, UUID],
        dataset_name: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[list[str]] = None,
        custom_function: Optional[Union[CustomFunction, UUID]] = None,
        runtime_name: Optional[str] = None,
        enclave: str = "",
    ) -> Job:
        user_code_id = self._resolve_usercode_id(user_code)
        custom_function_id = self._resolve_custom_func_id(custom_function)
        runtime_id = self._resolve_runtime_id(runtime_name)

        if enclave:
            self._verify_enclave(enclave)

        job_create = JobCreate(
            name=name,
            description=description,
            tags=tags if tags is not None else [],
            user_code_id=user_code_id,
            runtime_id=runtime_id,
            dataset_name=dataset_name,
            custom_function_id=custom_function_id,
            enclave=enclave,
        )
        job = self.rpc.job.create(job_create)

        return job

    def _get_results_from_dir(
        self,
        job: Job,
        results_dir: PathLike,
    ) -> JobResults:
        """Get the job results from the specified directory, and format it into a JobResults object."""
        results_dir = Path(results_dir)
        if not results_dir.exists():
            raise ValueError(
                f"Results directory {results_dir} does not exist for job {job.uid}"
            )

        output_dir = results_dir / "output"
        logs_dir = results_dir / "logs"
        expected_layout_msg = (
            f"{results_dir} should contain 'output' and 'logs' directories."
        )
        if not output_dir.exists():
            raise ValueError(
                f"Output directory {output_dir.name} does not exist for job {job.uid}. "
                + expected_layout_msg
            )
        if not logs_dir.exists():
            raise ValueError(
                f"Logs directory {logs_dir.name} does not exist for job {job.uid}. "
                + expected_layout_msg
            )

        return JobResults(
            job=job,
            results_dir=results_dir,
        )

    def review_results(
        self, job: Job, output_dir: Optional[PathLike] = None
    ) -> JobResults:
        if output_dir is None:
            output_dir = self._get_job_output_folder() / job.uid.hex
        return self._get_results_from_dir(job, output_dir)

    def share_results(self, job: Job) -> None:
        if not self.is_admin:
            raise RDSValidationError("Only admins can share results")
        job_results_folder = self._get_job_output_folder() / job.uid.hex
        output_path = self._share_result_files(job, job_results_folder)
        updated_job = self.rpc.job.update(
            JobUpdate(
                uid=job.uid,
                status=JobStatus.shared,
                error=job.error,
            )
        )
        job.apply_update(updated_job, in_place=True)
        logger.info(f"Shared results for job {job.uid} at {output_path}")

    def _share_result_files(self, job: Job, job_results_folder: Path) -> Path:
        syftbox_output_path = job.output_url.to_local_path(
            self.rds.syftbox_client.datasites
        )
        if not syftbox_output_path.exists():
            syftbox_output_path.mkdir(parents=True)

        # Copy all contents from job_output_folder to the output path
        for item in job_results_folder.iterdir():
            if item.is_file():
                shutil.copy2(item, syftbox_output_path)
            elif item.is_dir():
                shutil.copytree(
                    item,
                    syftbox_output_path / item.name,
                    dirs_exist_ok=True,
                )

        return syftbox_output_path

    def get_results(self, job: Job) -> JobResults:
        """Get the shared job results."""
        if job.status != JobStatus.shared:
            raise RDSValidationError(
                f"Job {job.uid} is not shared. Current status: {job.status}"
            )
        return self._get_results_from_dir(job, job.output_path)

    def get_logs(self, job: Union[Job, UUID, str]) -> dict[str, str]:
        """Get the stdout and stderr logs for a job.

        Args:
            job: Job object or UUID of the job

        Returns:
            dict with 'logs_dir', 'stdout', and 'stderr' keys
            Format matches get_output_dir() for consistency.

        Raises:
            ValueError: If logs directory doesn't exist
        """
        if isinstance(job, str):
            job = UUID(job)

        if isinstance(job, UUID):
            job = self.get(uid=job, mode="local")

        logs_dir = (self._get_job_output_folder() / job.uid.hex / "logs").resolve()

        if not logs_dir.exists():
            raise ValueError(
                f"Logs directory does not exist for job {job.uid} at {logs_dir}. "
                f"Job may not have been executed yet."
            )

        stdout_file = logs_dir / "stdout.log"
        stderr_file = logs_dir / "stderr.log"

        return {
            "logs_dir": str(logs_dir),
            "stdout": stdout_file.read_text() if stdout_file.exists() else "",
            "stderr": stderr_file.read_text() if stderr_file.exists() else "",
        }

    def get_output_dir(self, job: Union[Job, UUID, str]) -> dict[str, Any]:
        """Get the output directory and all files for a job.

        Args:
            job: Job object or UUID of the job

        Returns:
            dict with 'output_dir' (str) and 'files' (dict mapping relative_path to content)
            Format matches get_job_code() for consistency with rds-dashboard.

        Raises:
            ValueError: If output directory doesn't exist
        """
        if isinstance(job, str):
            job = UUID(job)

        if isinstance(job, UUID):
            job = self.get(uid=job, mode="local")

        output_dir = (self._get_job_output_folder() / job.uid.hex / "output").resolve()

        if not output_dir.exists():
            raise ValueError(
                f"Output directory does not exist for job {job.uid} at {output_dir}. "
                f"Job may not have been executed yet or produced no output."
            )

        # Read all files recursively (skip directories - frontend builds tree from paths)
        files = {}
        for file_path in output_dir.rglob("*"):
            # Skip directories - frontend will infer them from file paths
            if file_path.is_dir():
                continue

            relative_path = str(file_path.relative_to(output_dir))

            # Try to read as text, fall back to binary/error indicator
            try:
                files[relative_path] = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                # File contains non-UTF-8 bytes (binary file)
                try:
                    file_size = file_path.stat().st_size
                    size_str = (
                        f"{file_size / (1024**2):.2f} MB"
                        if file_size > 1024 * 1024
                        else f"{file_size / 1024:.2f} KB"
                        if file_size > 1024
                        else f"{file_size} bytes"
                    )
                    files[relative_path] = (
                        f"This file cannot be displayed as it contains non-UTF-8 bytes. File size: {size_str}."
                    )
                    logger.debug(f"Binary file detected: {file_path} ({size_str})")
                except Exception as size_error:
                    files[relative_path] = (
                        "This file cannot be displayed as it contains non-UTF-8 bytes."
                    )
                    logger.debug(
                        f"Binary file detected: {file_path} (size unavailable: {size_error})"
                    )
            except Exception as e:
                # Other errors (permission, I/O errors, etc.)
                logger.warning(f"Error reading {file_path}: {e}")
                try:
                    file_size = file_path.stat().st_size
                    size_str = (
                        f"{file_size / (1024**2):.2f} MB"
                        if file_size > 1024 * 1024
                        else f"{file_size / 1024:.2f} KB"
                        if file_size > 1024
                        else f"{file_size} bytes"
                    )
                    files[relative_path] = f"Error reading file ({size_str}): {str(e)}"
                except Exception:
                    files[relative_path] = f"Error reading file: {str(e)}"

        return {
            "output_dir": str(output_dir),
            "files": files,
        }

    def show_logs(
        self,
        job: Union[Job, UUID, str],
        show_stdout: bool = True,
        show_stderr: bool = True,
    ) -> None:
        """Display the stdout and stderr logs for a job in a formatted way.

        Args:
            job: Job object or UUID of the job
            show_stdout: Whether to display stdout logs (default: True)
            show_stderr: Whether to display stderr logs (default: True)

        Raises:
            ValueError: If logs directory doesn't exist
        """
        if isinstance(job, str):
            job = UUID(job)

        logs = self.get_logs(job)

        # Try to use IPython display if available (for Jupyter notebooks)
        try:
            from IPython.display import HTML, display
            import uuid

            html_parts = []

            # Add JavaScript for copy functionality (only once)
            copy_script = """
            <script>
            function copyToClipboard(elementId, buttonId) {
                const text = document.getElementById(elementId).textContent;
                navigator.clipboard.writeText(text).then(function() {
                    const button = document.getElementById(buttonId);
                    const originalText = button.innerHTML;
                    button.innerHTML = '✓ Copied!';
                    button.style.backgroundColor = '#4caf50';
                    setTimeout(function() {
                        button.innerHTML = originalText;
                        button.style.backgroundColor = '#555';
                    }, 2000);
                }).catch(function(err) {
                    console.error('Failed to copy: ', err);
                });
            }
            </script>
            """
            html_parts.append(copy_script)

            if show_stdout and logs["stdout"]:
                stdout_id = f"stdout_{uuid.uuid4().hex[:8]}"
                copy_btn_id = f"copy_stdout_{uuid.uuid4().hex[:8]}"
                # Escape HTML in logs to prevent injection
                escaped_stdout = html.escape(logs["stdout"])

                stdout_html = f"""
                <div style="margin-bottom: 20px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                        <h3 style="color: #4caf50; margin: 0;">📄 STDOUT</h3>
                        <button id="{copy_btn_id}"
                                onclick="copyToClipboard('{stdout_id}', '{copy_btn_id}')"
                                style="background-color: #555; color: white; border: none;
                                       padding: 8px 16px; border-radius: 4px; cursor: pointer;
                                       font-size: 12px; transition: all 0.3s;">
                            📋 Copy
                        </button>
                    </div>
                    <pre id="{stdout_id}" style="background-color: #1e1e1e;
                                color: #e0e0e0;
                                padding: 15px; border-radius: 5px;
                                border-left: 4px solid #4caf50; overflow-x: auto;
                                font-family: 'Courier New', monospace; font-size: 12px;">{escaped_stdout}</pre>
                </div>
                """
                html_parts.append(stdout_html)

            if show_stderr and logs["stderr"]:
                stderr_id = f"stderr_{uuid.uuid4().hex[:8]}"
                copy_btn_id = f"copy_stderr_{uuid.uuid4().hex[:8]}"
                # Escape HTML in logs to prevent injection
                escaped_stderr = html.escape(logs["stderr"])

                stderr_html = f"""
                <div style="margin-bottom: 20px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                        <h3 style="color: #ff5252; margin: 0;">🛠️ STDERR</h3>
                        <button id="{copy_btn_id}"
                                onclick="copyToClipboard('{stderr_id}', '{copy_btn_id}')"
                                style="background-color: #555; color: white; border: none;
                                       padding: 8px 16px; border-radius: 4px; cursor: pointer;
                                       font-size: 12px; transition: all 0.3s;">
                            📋 Copy
                        </button>
                    </div>
                    <pre id="{stderr_id}" style="background-color: #1e1e1e;
                                color: #e0e0e0;
                                padding: 15px; border-radius: 5px;
                                border-left: 4px solid #ff5252; overflow-x: auto;
                                font-family: 'Courier New', monospace; font-size: 12px;">{escaped_stderr}</pre>
                </div>
                """
                html_parts.append(stderr_html)

            if not html_parts or len(html_parts) == 1:  # Only script, no logs
                display(HTML("<p><i>No logs to display</i></p>"))
            else:
                display(HTML("".join(html_parts)))

        except ImportError:
            # Fallback to plain text for console environments
            separator = "=" * 80

            if show_stdout and logs["stdout"]:
                print(f"\n{separator}")
                print("📄 STDOUT")
                print(separator)
                print(logs["stdout"])

            if show_stderr and logs["stderr"]:
                print(f"\n{separator}")
                print("🛠️ STDERR")
                print(separator)
                print(logs["stderr"])

            if not logs["stdout"] and not logs["stderr"]:
                print("\nNo logs to display")

    def approve(self, job: Job) -> Job:
        if not self.is_admin:
            raise RDSValidationError("Only admins can approve jobs")
        job_update = job.get_update_for_approve()
        updated_job = self.rpc.job.update(job_update)
        job.apply_update(updated_job, in_place=True)
        return job

    def reject(self, job: Job, reason: str = "Unspecified") -> None:
        if not self.is_admin:
            raise RDSValidationError("Only admins can reject jobs")

        allowed_statuses = (
            JobStatus.pending_code_review,
            JobStatus.job_run_finished,
            JobStatus.job_run_failed,
        )
        if job.status not in allowed_statuses:
            raise ValueError(f"Cannot reject job with status: {self.status}")

        error = (
            JobErrorKind.failed_code_review
            if job.status == JobStatus.pending_code_review
            else JobErrorKind.failed_output_review
        )

        job_update = JobUpdate(
            uid=job.uid,
            status=JobStatus.rejected,
            error=error,
            error_message=reason,
        )

        updated_job = self.rpc.job.update(job_update)
        job.apply_update(updated_job, in_place=True)

    def update_job_status(self, job_update: JobUpdate, job: Job) -> Job:
        new_job = self.rpc.job.update(job_update)
        return job.apply_update(new_job)

    def delete(
        self, job: Union[Job, UUID, str], delete_orphaned_usercode: bool = True
    ) -> bool:
        """Delete a single job by Job object or UUID.

        Args:
            job: Job object or UUID of the job to delete
            delete_orphaned_usercode: If True, also delete UserCode if not used by other jobs

        Returns:
            True if deletion was successful

        Raises:
            RDSValidationError: If user is not admin
        """
        if not self.is_admin:
            raise RDSValidationError("Only admins can delete jobs")

        if isinstance(job, str):
            job = UUID(job)

        # Get the full job object if we only have UUID
        if isinstance(job, UUID):
            try:
                job = self.get(uid=job, mode="local")
            except ValueError:
                logger.warning(f"Job {job} not found for deletion")
                return False

        # Delete job output folders
        self._delete_job_outputs(job)

        # Delete Job YAML file from local store
        deleted = self.local_store.job.delete_by_id(job.uid)
        if not deleted:
            logger.warning(f"Job {job.uid} not found for deletion")
            return False

        logger.info(f"Deleted job {job.uid} successfully")

        # Conditionally delete orphaned UserCode
        if delete_orphaned_usercode and job.user_code_id:
            self._delete_orphaned_usercode(job.user_code_id, job.uid)

        return True

    def delete_all(self, delete_orphaned_usercode: bool = True, **filters) -> int:
        """Delete all jobs matching the given filters.

        Args:
            delete_orphaned_usercode: If True, also delete UserCode if not used by other jobs
            **filters: Filter criteria for jobs to delete (e.g., status=JobStatus.rejected)

        Returns:
            Number of jobs deleted

        Raises:
            RDSValidationError: If user is not admin
        """
        if not self.is_admin:
            raise RDSValidationError("Only admins can delete jobs")

        # Get all jobs matching the filters
        jobs_to_delete = self.get_all(mode="local", **filters)

        deleted_count = 0
        for job in jobs_to_delete:
            if self.delete(job, delete_orphaned_usercode=delete_orphaned_usercode):
                deleted_count += 1

        logger.info(f"Deleted {deleted_count} jobs out of {len(jobs_to_delete)} found")
        return deleted_count

    def _delete_job_outputs(self, job: Job) -> None:
        """Delete job output folders."""
        # Delete job output folder using the job's output_url
        if job.output_url:
            job_output_path = job.output_url.to_local_path(
                self.syftbox_client.datasites
            )
            if job_output_path.exists():
                shutil.rmtree(job_output_path)
                logger.debug(f"Deleted job output path: {job_output_path}")

        # Delete job results from runner output folder
        job_runner_output = self._get_job_output_folder() / job.uid.hex
        if job_runner_output.exists():
            shutil.rmtree(job_runner_output)
            logger.debug(f"Deleted job runner output: {job_runner_output}")

    def _delete_orphaned_usercode(
        self, user_code_id: UUID, excluded_job_uid: UUID
    ) -> None:
        """Delete UserCode if it's not used by any other jobs."""
        # Check if UserCode is used by other jobs
        other_jobs = [
            j
            for j in self.get_all(mode="local", user_code_id=user_code_id)
            if j.uid != excluded_job_uid
        ]

        if other_jobs:
            logger.debug(
                f"UserCode {user_code_id} is still used by {len(other_jobs)} other job(s)"
            )
            return

        # UserCode is orphaned, delete it
        try:
            usercode = self.rds.user_code.get(uid=user_code_id, mode="local")

            # Delete UserCode files
            if usercode.dir_url:
                usercode_path = usercode.dir_url.to_local_path(
                    self.syftbox_client.datasites
                )
                if usercode_path.exists():
                    shutil.rmtree(usercode_path)
                    logger.debug(f"Deleted UserCode folder: {usercode_path}")

            # Delete UserCode YAML
            if self.local_store.user_code.delete_by_id(user_code_id):
                logger.debug(f"Deleted orphaned UserCode {user_code_id}")
        except Exception as e:
            logger.warning(f"Failed to delete orphaned UserCode {user_code_id}: {e}")

    def _get_job_output_folder(self) -> Path:
        """Get the job output folder, raising an error if not configured."""
        job_output_folder = self.config.runner_config.job_output_folder
        if job_output_folder is None:
            raise RDSValidationError(
                "job_output_folder is not configured. "
                "Please use init_session() to properly initialize the RDSClient."
            )
        return job_output_folder
