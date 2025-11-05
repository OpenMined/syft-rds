"""Simple test script that requires colorama (not in default dependencies)."""

import os
from pathlib import Path

# This will fail without UV installing dependencies from pyproject.toml
from colorama import Fore, Back, init

# Initialize colorama
init(autoreset=True)


def main():
    """Simple test to verify UV installed colorama dependency."""
    output_dir = Path(os.getenv("OUTPUT_DIR", "."))

    # Print colored output to demonstrate colorama is working
    print(f"{Fore.GREEN}✓ SUCCESS: colorama dependency was installed by UV!")
    print(
        f"{Fore.CYAN}This script requires colorama, which is not in syft-rds dependencies"
    )
    print(f"{Fore.YELLOW}UV automatically installed it from pyproject.toml")

    # Create a simple output file
    output_file = output_dir / "result.txt"
    output_file.write_text("UV dependency test passed!\n")

    print(f"{Fore.MAGENTA}Output written to: {output_file}")
    print(f"{Back.GREEN}{Fore.BLACK} JOB COMPLETED SUCCESSFULLY ")


if __name__ == "__main__":
    print(f"{Fore.BLUE}{'='*60}")
    print(f"{Fore.BLUE}UV Dependency Installation Test")
    print(f"{Fore.BLUE}{'='*60}")
    main()
    print(f"{Fore.GREEN}✓ Test completed - UV runtime working correctly!")
