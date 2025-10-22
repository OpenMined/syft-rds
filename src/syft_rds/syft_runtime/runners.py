from __future__ import annotations

import os
import shlex
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Type

from loguru import logger

from syft_rds.models import (
    DockerMount,
    Job,
    JobConfig,
    JobUpdate,
    PythonRuntimeConfig,
    RuntimeKind,
)
from syft_rds.syft_runtime.mounts import get_mount_provider
from syft_rds.syft_runtime.output_handlers import JobOutputHandler, parse_log_level


DEFAULT_WORKDIR = "/app"
DEFAULT_OUTPUT_DIR = DEFAULT_WORKDIR + "/output"


def get_runner_cls(job_config: JobConfig) -> Type["JobRunner"]:
    """Factory to get the appropriate runner class for a job config."""
    runtime_kind = job_config.runtime.kind
    if runtime_kind == RuntimeKind.PYTHON:
        return PythonRunner
    elif runtime_kind == RuntimeKind.DOCKER:
        return DockerRunner
    else:
        raise NotImplementedError(f"Unsupported runtime kind: {runtime_kind}")


def _check_uv_available() -> tuple[bool, str | None]:
    """Check if uv command is available and get version.

    Returns:
        tuple[bool, str | None]: (is_available, version_string)
    """
    try:
        result = subprocess.run(
            ["uv", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            return True, version
        return False, None
    except FileNotFoundError:
        return False, None
    except Exception as e:
        logger.warning(f"Failed to check uv availability: {e}")
        return False, None


class JobRunner:
    """Base class for running jobs."""

    def __init__(
        self,
        handlers: list[JobOutputHandler],
        update_job_status_callback: Callable[[JobUpdate, Job], Job | None],
    ):
        self.handlers = handlers
        self.update_job_status_callback = update_job_status_callback

    def run(
        self,
        job: Job,
        job_config: JobConfig,
    ) -> tuple[int, str | None] | subprocess.Popen:
        """Run a job
        Returns:
            tuple[int, str | None]: (blocking mode) The return code and error message
                if the job failed, otherwise None.
            subprocess.Popen: (non-blocking mode) The process object.
        """
        raise NotImplementedError

    def _prepare_job_folders(self, job_config: JobConfig) -> None:
        """Create necessary job folders"""
        job_config.job_path.mkdir(parents=True, exist_ok=True)
        job_config.logs_dir.mkdir(exist_ok=True)
        job_config.output_dir.mkdir(exist_ok=True)
        os.chmod(job_config.output_dir, 0o777)

    def _validate_paths(self, job_config: JobConfig) -> None:
        """Validate that the necessary paths exist and are of the correct type."""
        if not job_config.function_folder.exists():
            raise ValueError(
                f"Function folder {job_config.function_folder} does not exist"
            )
        # data_path is optional - only validate if provided
        if job_config.data_path is not None and not job_config.data_path.exists():
            raise ValueError(f"Dataset folder {job_config.data_path} does not exist")

    def _run_subprocess(
        self,
        cmd: list[str],
        job_config: JobConfig,
        job: Job,
        env: dict | None = None,
        blocking: bool = True,
    ) -> tuple[int, str | None] | subprocess.Popen:
        """
        Returns:
            tuple[int, str | None]: (blocking mode) The return code and error message
                if the job failed, otherwise None.
            subprocess.Popen: (non-blocking mode) The process object.
        """
        if self.update_job_status_callback:
            job_update = job.get_update_for_in_progress()
            self.update_job_status_callback(job_update, job)

        # Enable real-time output by writing directly to log files
        # This eliminates pipe buffering issues
        if env is None:
            env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        # Open log files for direct subprocess output (line buffered for real-time writes)
        stdout_log_path = job_config.logs_dir / "stdout.log"
        stderr_log_path = job_config.logs_dir / "stderr.log"
        stdout_file = open(stdout_log_path, "w", buffering=1)
        stderr_file = open(stderr_log_path, "w", buffering=1)

        for handler in self.handlers:
            handler.on_job_start(job_config)

        try:
            process = subprocess.Popen(
                cmd,
                stdout=stdout_file,  # Write directly to file
                stderr=stderr_file,  # Write directly to file
                text=True,
                env=env,
            )

            if blocking:
                logger.info("Running job in blocking mode")
                return self._run_blocking(
                    process, job, job_config, stdout_file, stderr_file
                )
            else:
                logger.info("Running job in non-blocking mode")
                # Store file handles for cleanup later
                process._log_files = (stdout_file, stderr_file)
                return process
        except Exception:
            # Clean up files if process creation fails
            stdout_file.close()
            stderr_file.close()
            raise

    def _run_blocking(
        self,
        process: subprocess.Popen,
        job: Job,
        job_config: JobConfig,
        stdout_file,
        stderr_file,
    ) -> tuple[int, str | None]:
        """Wait for process to complete while tailing logs in real-time."""
        # Create stop event for tailing threads
        stop_event = threading.Event()

        # Start threads to tail log files and stream to handlers
        stdout_log_path = job_config.logs_dir / "stdout.log"
        stderr_log_path = job_config.logs_dir / "stderr.log"

        stdout_thread = threading.Thread(
            target=_tail_file,
            args=(stdout_log_path, self.handlers, stop_event, False),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_tail_file,
            args=(stderr_log_path, self.handlers, stop_event, True),
            daemon=True,
        )

        # Start tailing threads
        stdout_thread.start()
        stderr_thread.start()

        try:
            # Wait for process to complete
            return_code = process.wait()
            logger.debug(
                f"Process {process.pid} terminated with return code {return_code}"
            )
        finally:
            # Stop tailing threads
            stop_event.set()

            # Close log files to ensure all data is flushed
            stdout_file.close()
            stderr_file.close()

            # Wait for tailing threads to finish (with timeout)
            stdout_thread.join(timeout=2.0)
            stderr_thread.join(timeout=2.0)

        # Read log files to check for errors
        stderr_logs = []
        error_logs = []

        if stderr_log_path.exists():
            with open(stderr_log_path, "r", errors="replace") as f:
                for line in f:
                    stderr_logs.append(line.rstrip("\n"))
                    # Check if this is an actual ERROR log
                    log_level, _ = parse_log_level(line)
                    if log_level in ("ERROR", "CRITICAL"):
                        error_logs.append(line.rstrip("\n"))

        logger.debug(f"Return code: {return_code}")
        error_message = None

        # Build error message from actual ERROR logs or all stderr if job failed
        if return_code != 0:
            # Job failed: include all stderr
            if stderr_logs:
                logger.debug(f"Job failed with stderr: {len(stderr_logs)} lines")
                error_message = "\n".join(stderr_logs)
        elif error_logs:
            # Job succeeded but had ERROR logs: treat as failure
            logger.debug(f"Job succeeded but found {len(error_logs)} ERROR-level logs")
            error_message = "\n".join(error_logs)
            return_code = 1

        # Notify handlers of completion
        for handler in self.handlers:
            handler.on_job_completion(return_code)

        return return_code, error_message


class PythonRunner(JobRunner):
    """Runs a Python job in a local subprocess."""

    def run(
        self,
        job: Job,
        job_config: JobConfig,
    ) -> tuple[int, str | None] | subprocess.Popen:
        """Run a job"""
        self._validate_paths(job_config)
        self._prepare_job_folders(job_config)

        cmd = self._prepare_run_command(job_config)

        env = os.environ.copy()
        env.update(job_config.get_env())
        env.update(job_config.extra_env)

        return self._run_subprocess(
            cmd, job_config, job, env=env, blocking=job_config.blocking
        )

    def _prepare_run_command(self, job_config: JobConfig) -> list[str]:
        script_path = Path(job_config.function_folder) / job_config.args[0]

        # Check if we should use uv run (when pyproject.toml exists and use_uv=True)
        runtime_config = job_config.runtime.config
        pyproject_path = job_config.function_folder / "pyproject.toml"

        if (
            isinstance(runtime_config, PythonRuntimeConfig)
            and runtime_config.use_uv
            and pyproject_path.exists()
        ):
            # Check if uv is available before attempting to use it
            uv_available, uv_version = _check_uv_available()
            if not uv_available:
                raise RuntimeError(
                    "uv command not found but required for this job. "
                    "Please install uv: https://docs.astral.sh/uv/getting-started/installation/"
                )

            logger.info(f"Using uv ({uv_version}) for job execution")
            logger.debug(f"Using 'uv run' for job execution (found {pyproject_path})")

            # Build command with UV-specific arguments
            cmd = ["uv", "run"]

            # Add user-provided UV arguments (e.g., --active)
            if job_config.uv_args:
                cmd.extend(job_config.uv_args)
                logger.debug(f"Using UV args: {job_config.uv_args}")

            # Add --frozen if uv.lock exists (speeds up subsequent runs)
            uv_lock_path = job_config.function_folder / "uv.lock"
            if uv_lock_path.exists():
                cmd.append("--frozen")
                logger.debug(f"Using --frozen flag (found {uv_lock_path})")

            cmd.extend(
                [
                    "--directory",
                    str(job_config.function_folder),
                    "python",
                    "-u",  # Force unbuffered output for real-time streaming
                    str(script_path),
                    *job_config.args[1:],
                ]
            )

            # Format command as shell string for cleaner logs
            cmd_str = " ".join(shlex.quote(str(arg)) for arg in cmd)
            logger.debug(f"Run command: {cmd_str}")

            return cmd
        else:
            # Fallback to regular python execution
            logger.debug("Using standard Python execution")
            cmd = [
                *job_config.runtime.cmd,
                "-u",  # Force unbuffered output for real-time streaming
                str(script_path),
                *job_config.args[1:],
            ]

            # Format command as shell string for cleaner logs
            cmd_str = " ".join(shlex.quote(str(arg)) for arg in cmd)
            logger.debug(f"Run command: {cmd_str}")

            return cmd


class DockerRunner(JobRunner):
    """Runs a job in a Docker container."""

    def run(
        self,
        job: Job,
        job_config: JobConfig,
    ) -> tuple[int, str | None] | subprocess.Popen:
        """Run a job in a Docker container"""
        logger.debug(
            f"Running code in '{job_config.function_folder}' on dataset '{job_config.data_path}' with runtime '{job_config.runtime.kind.value}'"
        )

        self._validate_paths(job_config)
        self._prepare_job_folders(job_config)

        self._check_docker_daemon(job)
        self._check_or_build_image(job_config, job)

        cmd = self._prepare_run_command(job_config)

        return self._run_subprocess(cmd, job_config, job, blocking=job_config.blocking)

    def _check_docker_daemon(self, job: Job) -> None:
        """Check if the Docker daemon is running."""
        try:
            process = subprocess.run(
                ["docker", "info"],
                check=True,
                capture_output=True,
            )
        except Exception as e:
            if self.update_job_status_callback:
                job_update = job.get_update_for_return_code(
                    return_code=process.returncode,
                    error_message="Docker daemon is not running with error: " + str(e),
                )
                self.update_job_status_callback(job_update, job)
            raise RuntimeError("Docker daemon is not running with error: " + str(e))

    def _get_image_name(self, job_config: JobConfig) -> str:
        """Get the Docker image name from the config or use the default."""
        runtime_config = job_config.runtime.config
        if not runtime_config.image_name:
            return job_config.runtime.name
        return runtime_config.image_name

    def _check_or_build_image(self, job_config: JobConfig, job: Job) -> None:
        """Check if the Docker image exists, otherwise build it."""
        image_name = self._get_image_name(job_config)
        result = subprocess.run(
            ["docker", "image", "inspect", image_name],
            capture_output=True,
            check=False,
            text=True,
        )
        if result.returncode == 0:
            logger.info(f"Docker image '{image_name}' already exists.")
            return

        logger.info(f"Docker image '{image_name}' not found. Building it now...")
        self._build_docker_image(job_config, job)

    def _build_docker_image(self, job_config: JobConfig, job: Job) -> None:
        """Build the Docker image."""
        image_name = self._get_image_name(job_config)
        dockerfile_content: str = job_config.runtime.config.dockerfile_content
        error_for_job: str | None = None
        build_context = "."
        try:
            build_cmd = [
                "docker",
                "build",
                "-t",
                image_name,
                "-f",
                "-",  # Use stdin for Dockerfile content
                str(build_context),
            ]
            logger.debug(
                f"Running docker build command: {' '.join(build_cmd)}\nDockerfile content:\n{dockerfile_content}"
            )
            process = subprocess.run(
                build_cmd,
                input=dockerfile_content,
                capture_output=True,
                check=True,
                text=True,
            )

            logger.debug(process.stdout)
            logger.info(f"Successfully built Docker image '{image_name}'.")
        except FileNotFoundError:
            raise RuntimeError("Docker not installed or not in PATH.")
        except subprocess.CalledProcessError as e:
            error_message = f"Failed to build Docker image '{image_name}'."
            logger.error(f"{error_message} stderr: {e.stderr}")
            error_for_job = f"{error_message}\n{e.stderr}"

            # Update job status if callback is available
            if self.update_job_status_callback:
                job_failed = job.get_update_for_return_code(
                    return_code=e.returncode,
                    error_message=error_for_job,
                )
                self.update_job_status_callback(job_failed, job)

            raise RuntimeError(f"Failed to build Docker image '{image_name}'.")
        except Exception as e:
            raise RuntimeError(f"An error occurred during Docker image build: {e}")

    def _get_extra_mounts(self, job_config: JobConfig) -> list[DockerMount]:
        """Get extra mounts for a job"""
        docker_runtime_config = job_config.runtime.config
        if docker_runtime_config.app_name is None:
            return []
        mount_provider = get_mount_provider(docker_runtime_config.app_name)
        if mount_provider:
            return mount_provider.get_mounts(job_config)
        return []

    def _prepare_run_command(self, job_config: JobConfig) -> list[str]:
        """Build the Docker run command with security constraints"""
        image_name = self._get_image_name(job_config)
        docker_mounts = [
            "-v",
            f"{Path(job_config.function_folder).absolute()}:{DEFAULT_WORKDIR}/code:ro",
        ]

        # Only mount data directory if data_path is provided
        if job_config.data_path is not None:
            docker_mounts.extend(
                [
                    "-v",
                    f"{Path(job_config.data_path).absolute()}:{DEFAULT_WORKDIR}/data:ro",
                ]
            )

        docker_mounts.extend(
            [
                "-v",
                f"{job_config.output_dir.absolute()}:{DEFAULT_OUTPUT_DIR}:rw",
            ]
        )

        extra_mounts = self._get_extra_mounts(job_config)
        if extra_mounts:
            for mount in extra_mounts:
                docker_mounts.extend(
                    [
                        "-v",
                        f"{mount.source.resolve()}:{mount.target}:{mount.mode}",
                    ]
                )

        interpreter = " ".join(job_config.runtime.cmd)
        interpreter_str = f'"{interpreter}"' if " " in interpreter else interpreter

        limits = [
            # Security constraints
            "--cap-drop",
            "ALL",  # Drop all capabilities
            "--network",
            "none",  # Disable networking
            # "--read-only",  # Read-only root filesystem - TODO: re-enable this
            "--tmpfs",
            "/tmp:size=16m,noexec,nosuid,nodev",  # Secure temp directory
            # Resource limits
            "--memory",
            "1G",
            "--cpus",
            "1",
            "--pids-limit",
            "100",
            "--ulimit",
            "nproc=4096:4096",
            "--ulimit",
            "nofile=50:50",
            "--ulimit",
            "fsize=10000000:10000000",  # ~10MB file size limit
        ]

        # Base environment variables
        env_args = [
            "-e",
            f"TIMEOUT={job_config.timeout}",
            "-e",
            f"OUTPUT_DIR={DEFAULT_OUTPUT_DIR}",
            "-e",
            f"INTERPRETER={interpreter_str}",
            "-e",
            f"INPUT_FILE='{DEFAULT_WORKDIR}/code/{job_config.args[0]}'",
        ]

        # Only add DATA_DIR if data_path is provided
        if job_config.data_path is not None:
            env_args.extend(
                [
                    "-e",
                    f"DATA_DIR={job_config.data_mount_dir}",
                ]
            )

        docker_run_cmd = [
            "docker",
            "run",
            "--rm",  # Remove container after completion
            *limits,
            *env_args,
            *job_config.get_extra_env_as_docker_args(),
            *docker_mounts,
            "--workdir",
            DEFAULT_WORKDIR,
            image_name,
            f"{DEFAULT_WORKDIR}/code/{job_config.args[0]}",
            *job_config.args[1:],
        ]
        logger.debug(f"Docker run command: {docker_run_cmd}")
        return docker_run_cmd


def _tail_file(
    file_path: Path,
    handlers: list[JobOutputHandler],
    stop_event: threading.Event,
    is_stderr: bool = False,
    poll_interval: float = 0.1,
) -> None:
    """
    Tail a file in real-time and call handlers with new lines.

    This function runs in a background thread and follows a log file like `tail -f`,
    calling handler.on_job_progress() for each new line that appears.

    Args:
        file_path: Path to the log file to tail
        handlers: List of output handlers to notify
        stop_event: Threading event to signal when to stop tailing
        is_stderr: Whether this is stderr (vs stdout)
        poll_interval: How often to check for new lines (seconds)
    """
    # Wait for file to be created
    max_wait = 5  # seconds
    wait_time = 0
    while not file_path.exists() and wait_time < max_wait:
        if stop_event.is_set():
            return
        time.sleep(0.1)
        wait_time += 0.1

    if not file_path.exists():
        logger.warning(f"Log file {file_path} was not created")
        return

    try:
        with open(file_path, "r", errors="replace") as f:
            # Start from beginning to catch any early output
            while not stop_event.is_set():
                line = f.readline()
                if line:
                    # Remove trailing newline for handler
                    line = line.rstrip("\n")
                    # Call handlers with new line
                    for handler in handlers:
                        if is_stderr:
                            handler.on_job_progress("", line + "\n")
                        else:
                            handler.on_job_progress(line + "\n", "")
                else:
                    # No new line, sleep briefly
                    time.sleep(poll_interval)
    except Exception as e:
        logger.error(f"Error tailing {file_path}: {e}")
