from typing_extensions import Protocol, Optional
import re
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner

from syft_rds.models import JobConfig, PythonRuntimeConfig


def parse_log_level(line: str) -> tuple[str | None, str]:
    """
    Parse log level from a log line.

    Supports common formats:
    - Loguru: "2025-10-13 21:39:04.550 | INFO | module:function:28 - message"
    - Standard: "[INFO] message" or "INFO: message"

    Args:
        line: Log line to parse

    Returns:
        Tuple of (log_level, original_line)
        log_level is None if no level detected, otherwise one of: ERROR, WARNING, INFO, DEBUG
    """
    if not line or not line.strip():
        return None, line

    # Loguru format: "YYYY-MM-DD HH:MM:SS.mmm | LEVEL | ..."
    loguru_match = re.match(
        r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} \| (\w+)\s+\|", line
    )
    if loguru_match:
        level = loguru_match.group(1).upper()
        if level in (
            "ERROR",
            "CRITICAL",
            "WARNING",
            "INFO",
            "DEBUG",
            "TRACE",
            "SUCCESS",
        ):
            return level, line

    # Standard logging format: "[LEVEL]" or "LEVEL:"
    standard_match = re.match(r"^\[?(\w+)\]?\s*[:\-]", line)
    if standard_match:
        level = standard_match.group(1).upper()
        if level in ("ERROR", "CRITICAL", "WARNING", "WARN", "INFO", "DEBUG"):
            return "WARNING" if level == "WARN" else level, line

    return None, line


class JobOutputHandler(Protocol):
    """Protocol defining the interface for job output handling and display"""

    def on_job_start(self, job_config: JobConfig) -> None:
        """Display job configuration"""
        pass

    def on_job_progress(self, stdout: str, stderr: str) -> None:
        """Display job progress"""
        pass

    def on_job_completion(self, return_code: int) -> None:
        """Display job completion status"""
        pass


class FileOutputHandler(JobOutputHandler):
    """Writes initial job start message to log files.

    Note: The subprocess itself writes directly to log files for real-time streaming.
    This handler only writes the initial "Starting job..." message.
    """

    def __init__(self):
        pass

    def on_job_start(self, job_config: JobConfig) -> None:
        """Write initial message to log files before subprocess starts."""
        # Write "Starting job..." to both log files
        stdout_path = job_config.logs_dir / "stdout.log"
        stderr_path = job_config.logs_dir / "stderr.log"

        with open(stdout_path, "w") as f:
            f.write("Starting job...\n")

        with open(stderr_path, "w") as f:
            f.write("Starting job...\n")

    def on_job_progress(self, stdout: str, stderr: str) -> None:
        """No-op: subprocess writes directly to files."""
        pass

    def on_job_completion(self, return_code: int) -> None:
        """No-op: subprocess has already written all output."""
        pass


class RichConsoleUI(JobOutputHandler):
    """Rich console implementation of JobOutputHandler"""

    def __init__(self, show_stdout: bool = True, show_stderr: bool = True):
        self.show_stdout = show_stdout
        self.show_stderr = show_stderr
        self.console = Console()
        spinner = Spinner("dots")
        self.live = Live(spinner, refresh_per_second=10)

    def on_job_start(self, job_config: JobConfig) -> None:
        self.console.print(
            Panel.fit(
                "\n".join(
                    [
                        "[bold green]Starting job[/]",
                        f"[bold white]Execution:[/] [cyan]{_format_execution_command(job_config)}[/]",
                        f"[bold white]Dataset Dir:[/]  [cyan]{_format_path(job_config.data_path)}[/]",
                        f"[bold white]Output Dir:[/]   [cyan]{_format_path(job_config.output_dir)}[/]",
                        f"[bold white]Timeout:[/]  [cyan]{job_config.timeout}s[/]",
                    ]
                ),
                title="[bold]Job Configuration",
                border_style="cyan",
            )
        )
        try:
            self.live.start()
            self.live.console.print("[bold cyan]Running job...[/]")
        except Exception as e:
            self.console.print(f"[red]Error starting live: {e}[/]")

    def on_job_progress(self, stdout: str, stderr: str) -> None:
        # Update UI display
        if not self.live:
            return

        if stdout and self.show_stdout:
            self.live.console.print(stdout, end="")
        if stderr and self.show_stderr:
            # Parse log level to determine display style
            log_level, _ = parse_log_level(stderr)
            if log_level in ("ERROR", "CRITICAL"):
                # Actual error: show in bold red
                self.live.console.print(f"[bold red]{stderr}[/]", end="")
            elif log_level in ("WARNING", "WARN"):
                # Warning: show in yellow
                self.live.console.print(f"[yellow]{stderr}[/]", end="")
            elif log_level:
                # Other log levels (INFO, DEBUG, etc.): show in dim white
                self.live.console.print(f"[dim]{stderr}[/]", end="")
            else:
                # Unparsed stderr: show in red
                self.live.console.print(f"[red]{stderr}[/]", end="")

    def on_job_completion(self, return_code: int) -> None:
        # Update UI display
        if self.live:
            self.live.stop()

        if return_code == 0:
            self.console.print("\n[bold green]Job completed successfully![/]")
        else:
            self.console.print(
                f"\n[bold red]Job failed with return code {return_code}[/]"
            )

    def __del__(self):
        self.live.stop()


class TextUI(JobOutputHandler):
    """Simple text-based implementation of JobOutputHandler using print statements"""

    def __init__(self, show_stdout: bool = True, show_stderr: bool = True):
        self.show_stdout = show_stdout
        self.show_stderr = show_stderr
        self._job_running = False

    def on_job_start(self, config: JobConfig) -> None:
        first_line = "================ Job Configuration ================"
        last_line = "=" * len(first_line)

        # Build the output
        output_lines = [
            f"\n{first_line}",
            f"Execution:    {_format_execution_command(config)}",
            f"Dataset Dir: {_format_path(config.data_path)}",
            f"Output Dir:  {_format_path(config.output_dir)}",
            f"Timeout:      {config.timeout}s",
            f"{last_line}\n",
            "[STARTING JOB]",
        ]
        output_text = "\n".join(output_lines)
        print(output_text)

        self._job_running = True

    def on_job_progress(self, stdout: str, stderr: str) -> None:
        if not self._job_running:
            return
        if stdout and self.show_stdout:
            print(stdout, end="")
        if stderr and self.show_stderr:
            # Parse log level to determine if this is an actual error
            log_level, _ = parse_log_level(stderr)
            if log_level in ("ERROR", "CRITICAL"):
                # Actual error: show with [ERROR] prefix
                print(f"[ERROR] {stderr}", end="")
            elif log_level in ("WARNING", "WARN"):
                # Warning: show with [WARNING] prefix
                print(f"[WARNING] {stderr}", end="")
            elif log_level:
                # Other log levels (INFO, DEBUG, etc.): show without prefix
                print(stderr, end="")
            else:
                # Unparsed stderr: show with [STDERR] prefix
                print(f"[STDERR] {stderr}", end="")

    def on_job_completion(self, return_code: int) -> None:
        self._job_running = False
        if return_code == 0:
            print("\n[JOB COMPLETED SUCCESSFULLY]\n")
        else:
            print(f"\n[JOB FAILED] Return code: {return_code}\n")

    def __del__(self):
        self._job_running = False


# Helper function to format path for display
def _format_path(path: Optional[Path]) -> str:
    """Format a path for display. Paths are already absolute from JobConfig."""
    if path is None:
        return "—"
    return str(path)


def _format_execution_command(job_config: JobConfig) -> str:
    """Format the execution command for display, including UV if applicable."""
    runtime_config = job_config.runtime.config
    pyproject_path = job_config.function_folder / "pyproject.toml"

    # Check if UV is being used
    if (
        isinstance(runtime_config, PythonRuntimeConfig)
        and runtime_config.use_uv
        and pyproject_path.exists()
    ):
        cmd_parts = ["uv", "run"]

        # Add UV-specific arguments
        if job_config.uv_args:
            cmd_parts.extend(job_config.uv_args)

        # Add --frozen if uv.lock exists
        uv_lock_path = job_config.function_folder / "uv.lock"
        if uv_lock_path.exists():
            cmd_parts.append("--frozen")

        cmd_parts.extend(["--directory", "...", "python", "-u"])
        cmd_parts.extend(job_config.args)
    else:
        # Standard Python execution
        cmd_parts = [*job_config.runtime.cmd, "-u"]
        cmd_parts.extend(job_config.args)

    return " ".join(cmd_parts)
