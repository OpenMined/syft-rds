from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Callable, Type

from loguru import logger

from syft_rds.models import (
    DockerMount,
    Job,
    JobConfig,
    JobUpdate,
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
        if not job_config.data_path.exists():
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

        for handler in self.handlers:
            handler.on_job_start(job_config)

        # Enable real-time output streaming using multiple approaches:
        # 1. PYTHONUNBUFFERED=1 env var (fallback for edge cases)
        # 2. Python's -u flag in command (primary method, set in _prepare_run_command)
        # 3. bufsize=1 for line buffering on our subprocess pipes
        if env is None:
            env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # Line buffering for real-time output
            env=env,
        )

        if blocking:
            logger.info("Running job in blocking mode")
            return self._run_blocking(process, job)
        else:
            logger.info("Running job in non-blocking mode")
            return process

    def _run_blocking(
        self,
        process: subprocess.Popen,
        job: Job,
    ) -> tuple[int, str | None]:
        stderr_logs = []
        error_logs = []  # Track actual ERROR-level logs

        # Stream logs
        while True:
            stdout_line = process.stdout.readline()
            stderr_line = process.stderr.readline()
            if stderr_line:
                stderr_logs.append(stderr_line)
                # Check if this is an actual ERROR log
                log_level, _ = parse_log_level(stderr_line)
                if log_level in ("ERROR", "CRITICAL"):
                    error_logs.append(stderr_line)
            if stdout_line or stderr_line:
                for handler in self.handlers:
                    handler.on_job_progress(stdout_line, stderr_line)
            if process.poll() is not None:
                logger.debug(
                    f"Process {process.pid} terminated with return code {process.returncode}"
                )
                break
            time.sleep(0.1)

        # Flush remaining output
        for line in process.stdout:
            for handler in self.handlers:
                handler.on_job_progress(line, "")
        for line in process.stderr:
            stderr_logs.append(line)
            # Check if this is an actual ERROR log
            log_level, _ = parse_log_level(line)
            if log_level in ("ERROR", "CRITICAL"):
                error_logs.append(line)
            for handler in self.handlers:
                handler.on_job_progress("", line)

        return_code = process.returncode
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

        # Handle job completion results
        for handler in self.handlers:
            handler.on_job_completion(process.returncode)

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

        if runtime_config.use_uv and pyproject_path.exists():
            logger.debug(f"Using 'uv run' for job execution (found {pyproject_path})")
            return [
                "uv",
                "run",
                "--directory",
                str(job_config.function_folder),
                "python",
                "-u",  # Force unbuffered output for real-time streaming
                str(script_path),
                *job_config.args[1:],
            ]
        else:
            # Fallback to regular python execution
            logger.debug("Using standard Python execution")
            return [
                *job_config.runtime.cmd,
                "-u",  # Force unbuffered output for real-time streaming
                str(script_path),
                *job_config.args[1:],
            ]


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
            raise RuntimeError(f"Failed to build Docker image '{image_name}'.")
        except Exception as e:
            raise RuntimeError(f"An error occurred during Docker image build: {e}")
        finally:
            if error_for_job and self.update_job_status_callback:
                job_failed = job.get_update_for_return_code(
                    return_code=process.returncode,
                    error_message=error_for_job,
                )
                self.update_job_status_callback(job_failed, job)

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
            "-v",
            f"{Path(job_config.data_path).absolute()}:{DEFAULT_WORKDIR}/data:ro",
            "-v",
            f"{job_config.output_dir.absolute()}:{DEFAULT_OUTPUT_DIR}:rw",
        ]

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

        docker_run_cmd = [
            "docker",
            "run",
            "--rm",  # Remove container after completion
            *limits,
            # Environment variables
            "-e",
            f"TIMEOUT={job_config.timeout}",
            "-e",
            f"DATA_DIR={job_config.data_mount_dir}",
            "-e",
            f"OUTPUT_DIR={DEFAULT_OUTPUT_DIR}",
            "-e",
            f"INTERPRETER={interpreter_str}",
            "-e",
            f"INPUT_FILE='{DEFAULT_WORKDIR}/code/{job_config.args[0]}'",
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
