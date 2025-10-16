from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Union
from zipfile import ZipFile

PathLike = Union[str, Path]

# Default patterns to ignore when zipping code directories
DEFAULT_IGNORE_PATTERNS = [
    ".venv",
    "venv",
    "__pycache__",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".git",
    ".gitignore",
    ".DS_Store",
    "*.egg-info",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    ".ipynb_checkpoints",
    ".idea",
    ".vscode",
    "*.swp",
    "*.swo",
    "*~",
]


def _should_ignore(path: Path, base_dir: Path, ignore_patterns: List[str]) -> bool:
    """Check if a path should be ignored based on patterns.

    Args:
        path: Path to check
        base_dir: Base directory for relative path matching
        ignore_patterns: List of patterns to match (supports wildcards)

    Returns:
        True if path should be ignored
    """
    try:
        relative_path = path.relative_to(base_dir)
    except ValueError:
        # Path is not relative to base_dir, don't ignore
        return False

    # Check each part of the path against patterns
    for part in relative_path.parts:
        for pattern in ignore_patterns:
            # Direct match or glob pattern match
            if part == pattern or Path(part).match(pattern):
                return True

    # Also check the full relative path against patterns
    for pattern in ignore_patterns:
        if relative_path.match(pattern):
            return True

    return False


def extract_zip(zip_data: bytes, target_dir: PathLike) -> None:
    """Extract zip data to a target directory.

    Args:
        zip_data: Bytes containing zip content
        target_dir: Directory to extract files to
    """
    with ZipFile(BytesIO(zip_data)) as z:
        z.extractall(str(target_dir))


def zip_to_bytes(
    files_or_dirs: Union[PathLike, List[PathLike]],
    base_dir: Optional[PathLike] = None,
    ignore_patterns: Optional[List[str]] = None,
) -> bytes:
    """Create a zip file from files or directories, returning the zip content as bytes.

    Args:
        files_or_dirs: Single path or list of paths to include
        base_dir: Optional base directory for relative paths in the zip
        ignore_patterns: Optional list of patterns to ignore (e.g., '.venv', '*.pyc').
                        If None, uses DEFAULT_IGNORE_PATTERNS. Pass [] to ignore nothing.

    Returns:
        Bytes containing the zip file
    """
    buffer = BytesIO()

    # Use default ignore patterns if none provided
    if ignore_patterns is None:
        ignore_patterns = DEFAULT_IGNORE_PATTERNS

    with ZipFile(buffer, "w") as z:
        paths = (
            [files_or_dirs] if isinstance(files_or_dirs, (str, Path)) else files_or_dirs
        )

        for path in paths:
            path = Path(path)

            if not path.exists():
                raise FileNotFoundError(f"Path {path} does not exist.")
            if path.is_file():
                arcname = path.name if base_dir is None else path.relative_to(base_dir)
                z.write(path, arcname=str(arcname))
            elif path.is_dir():
                for file_path in path.rglob("*"):
                    if file_path.is_file():
                        # Check if file should be ignored
                        if ignore_patterns and _should_ignore(
                            file_path, path, ignore_patterns
                        ):
                            continue

                        arcname = (
                            file_path.name
                            if base_dir is None
                            else file_path.relative_to(base_dir)
                        )
                        z.write(file_path, arcname=str(arcname))

    return buffer.getvalue()


def get_files_from_zip(zip_data: bytes) -> Dict[str, bytes]:
    """Extract files from zip data to a dictionary.

    Args:
        zip_data: Bytes containing zip content

    Returns:
        Dictionary mapping filenames to file contents
    """
    result = {}
    with ZipFile(BytesIO(zip_data)) as z:
        for filename in z.namelist():
            result[filename] = z.read(filename)

    return result
