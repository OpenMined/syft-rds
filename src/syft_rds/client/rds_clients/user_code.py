import subprocess
from pathlib import Path

from loguru import logger

from syft_rds.client.rds_clients.base import RDSClientModule
from syft_rds.client.utils import PathLike
from syft_rds.models import (
    UserCode,
    UserCodeCreate,
    UserCodeType,
)
from syft_rds.utils.zip_utils import zip_to_bytes


class UserCodeRDSClient(RDSClientModule[UserCode]):
    ITEM_TYPE = UserCode

    def create(
        self,
        code_path: PathLike,
        name: str | None = None,
        entrypoint: str | None = None,
        ignore_patterns: list[str] | None = None,
    ) -> UserCode:
        """Create a new UserCode object from a file or directory.

        Args:
            code_path: Path to the code file or directory
            name: Optional name for the user code
            entrypoint: Entry point file for folder-type code (required for folders)
            ignore_patterns: Optional list of patterns to ignore when zipping.
                        If None, uses default ignore patterns (.venv, __pycache__, etc.).
                        Pass [] to include all files.

        Returns:
            UserCode: The created user code object

        Raises:
            FileNotFoundError: If code_path or entrypoint doesn't exist
            ValueError: If entrypoint is not provided for folder-type code
        """
        code_path = Path(code_path)
        if not code_path.exists():
            raise FileNotFoundError(f"Path {code_path} does not exist.")

        if code_path.is_dir():
            code_type = UserCodeType.FOLDER

            # Entrypoint is required for folder-type code
            if not entrypoint:
                raise ValueError("Entrypoint should be provided for folder code.")

            # Validate that the entrypoint exists within the folder
            if not (code_path / entrypoint).exists():
                raise FileNotFoundError(
                    f"Entrypoint {entrypoint} does not exist in {code_path}."
                )

            # Generate uv.lock if needed (ensures reproducible environments across DOs)
            _generate_uv_lock(code_path)

            files_zipped = zip_to_bytes(
                files_or_dirs=[code_path],
                base_dir=code_path,
                ignore_patterns=ignore_patterns,
            )
        else:
            code_type = UserCodeType.FILE

            # For file-type code, the entrypoint is the file name
            entrypoint = entrypoint or code_path.name

            # Single files don't need ignore patterns
            files_zipped = zip_to_bytes(files_or_dirs=code_path, ignore_patterns=[])

        user_code_create = UserCodeCreate(
            name=name,
            files_zipped=files_zipped,
            code_type=code_type,
            entrypoint=entrypoint,
        )

        user_code = self.rpc.user_code.create(user_code_create)

        return user_code


def _has_editable_dependencies(pyproject_path: Path) -> bool:
    """Check if pyproject.toml contains editable/path dependencies.

    Returns True if [tool.uv.sources] contains any entries with 'path' or 'editable' keys.
    These indicate local/editable dependencies that won't work across different filesystems.
    """

    try:
        import tomllib  # only available in Python 3.11+
    except ImportError:
        import tomli as tomllib

    try:
        with open(pyproject_path, "rb") as f:
            pyproject = tomllib.load(f)

        # Check for uv sources (where editable deps are defined)
        uv_sources = pyproject.get("tool", {}).get("uv", {}).get("sources", {})

        for source_name, source_config in uv_sources.items():
            if isinstance(source_config, dict):
                # Check if this source has 'path' or 'editable' keys
                if "path" in source_config or "editable" in source_config:
                    logger.debug(
                        f"Found editable dependency: {source_name} = {source_config}"
                    )
                    return True

        return False
    except Exception as e:
        logger.warning(
            f"Failed to parse pyproject.toml: {e}. Assuming no editable deps."
        )
        return False


def _generate_uv_lock(code_path: Path) -> None:
    """Generate uv.lock file if pyproject.toml exists and no lock file is present.

    Skips generation if editable dependencies are detected (dev mode).
    In production mode (PyPI-only deps), generates lock for reproducible environments.

    Args:
        code_path: Path to the code directory containing pyproject.toml
    """
    pyproject_path = code_path / "pyproject.toml"
    uv_lock_path = code_path / "uv.lock"

    if not pyproject_path.exists() or uv_lock_path.exists():
        return

    # Check for editable dependencies before generating lock
    if _has_editable_dependencies(pyproject_path):
        logger.debug(
            "Skipping lock generation: editable dependencies detected (dev mode). "
            "Each DO will generate its own lock file."
        )
        return

    # No editable deps - safe to generate portable lock file
    logger.info(
        f"Generating `uv.lock` for {code_path} to ensure reproducible environments"
    )
    try:
        subprocess.run(
            ["uv", "lock"],
            cwd=code_path,
            check=True,
            capture_output=True,
            text=True,
            timeout=120,  # 2 minute timeout
        )
        logger.success(
            "Generated `uv.lock`. All DOs will use identical dependency versions."
        )

    except subprocess.CalledProcessError as e:
        logger.warning(
            f"Failed to generate uv.lock: {e.stderr}. "
            "Each DO will generate its own lock (versions may differ)."
        )
    except FileNotFoundError:
        logger.warning(
            "uv not found. DOs will generate locks independently (versions may differ)."
        )
    except subprocess.TimeoutExpired:
        logger.warning(
            "Lock generation timed out. DOs will generate locks independently."
        )
