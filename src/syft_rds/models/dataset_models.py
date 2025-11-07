import os
from pathlib import Path
from typing_extensions import Optional
from uuid import UUID

from IPython.display import HTML, display
from loguru import logger
from pydantic import Field
from syft_core import SyftBoxURL

from syft_rds.display_utils.html_format import create_html_repr
from syft_rds.models.base import ItemBase, ItemBaseCreate, ItemBaseUpdate

SYFT_RDS_DATA_DIR = "SYFT_RDS_DATA_DIR"


class Dataset(ItemBase):
    __schema_name__ = "dataset"
    __table_extra_fields__ = [
        "name",
        "summary",
    ]

    name: str = Field(description="Name of the dataset.")
    private: SyftBoxURL = Field(description="Private Syft URL of the dataset.")
    mock: SyftBoxURL = Field(description="Mock Syft URL of the dataset.")
    summary: Optional[str] = Field(description="Summary string of the dataset.")
    readme: Optional[SyftBoxURL] = Field(
        description="REAMD.md Syft URL of the dataset."
    )
    tags: list[str] = Field(description="Tags for the dataset.")
    runtime_id: Optional[UUID] = Field(
        default=None, description="ID of the default runtime for the dataset."
    )
    auto_approval: list[str] = Field(
        default_factory=list,
        description="List of datasites whose jobs will be automatically approved.",
    )

    @property
    def mock_path(self) -> Path:
        return self.get_mock_path()

    @property
    def private_path(self) -> Path:
        return self.get_private_path()

    @property
    def readme_path(self) -> Optional[Path]:
        return self.get_readme_path()

    def get_mock_path(self) -> Path:
        mock_path: Path = self.mock.to_local_path(
            datasites_path=self._syftbox_client.datasites
        )
        if not mock_path.exists():
            raise FileNotFoundError(f"Mock file not found at {mock_path}")
        return mock_path

    def get_private_path(self) -> Path:
        """
        Will always raise PermissionError for non-admin users since they
        don't have permission to access private data.
        """
        # Check if user is admin before attempting to access private path
        if not self._is_admin():
            raise PermissionError(
                f"You must be the datasite admin to access private data. "
                f"Your SyftBox email: '{self._syftbox_client.email}'. "
                f"Host email: '{self._client.config.host}'"
            )
        # Private datasets are stored in ~/.syftbox/private_datasets/<email>/<dataset-name>
        # Use the same logic as DatasetPathManager.get_local_private_dataset_dir()
        home_dir = self._syftbox_client.config.data_dir.parent
        private_path = (
            home_dir
            / ".syftbox"
            / "private_datasets"
            / self._syftbox_client.email
            / self.name
        )

        if not private_path.exists():
            raise FileNotFoundError(
                f"Private data not found at {private_path}. "
                f"Probably you don't have admin permission to the dataset."
            )
        return private_path

    def get_readme_path(self) -> Optional[Path]:
        """
        Will always raise FileNotFoundError for non-admin since the
        private path will never by synced
        """
        if not self.readme:
            return None
        readme_path: Path = self.readme.to_local_path(
            datasites_path=self._syftbox_client.datasites
        )
        if not readme_path.exists():
            return None
        return readme_path

    def get_description(self) -> str:
        # read the description .md file
        if not self.readme:
            return "No description provided."
        readme_path = self.get_readme_path()
        if not readme_path:
            return "No description provided."
        with open(readme_path) as f:
            return f.read()

    def describe(self):
        field_to_include = [
            "uid",
            "created_at",
            "updated_at",
            "name",
            "readme_path",
            "mock_path",
        ]
        try:
            # Only include private path if it exists and user has permission
            _ = self.private_path
            field_to_include.append("private_path")
        except (FileNotFoundError, PermissionError):
            pass

        # Only include display paths that are not None
        display_paths = []
        if self.mock_path is not None:
            display_paths.append("mock_path")
        if self.readme_path is not None:
            display_paths.append("readme_path")

        description = create_html_repr(
            obj=self,
            fields=field_to_include,
            display_paths=display_paths,
        )

        display(HTML(description))

    def _is_admin(self) -> bool:
        """Check if the current user is admin by comparing email with host."""
        return self._client.email == self._client.host

    def set_env(self, mock: bool = True):
        if mock:
            os.environ[SYFT_RDS_DATA_DIR] = self.get_mock_path().as_posix()
        else:
            os.environ[SYFT_RDS_DATA_DIR] = self.get_private_path().as_posix()
        logger.info(
            f"Set {SYFT_RDS_DATA_DIR} to {os.environ[SYFT_RDS_DATA_DIR]} as mock={mock}"
        )


class DatasetUpdate(ItemBaseUpdate[Dataset]):
    name: Optional[str] = None
    path: Optional[str] = Field(
        description="Path of the new private dataset directory", default=None
    )
    summary: Optional[str] = None
    auto_approval: Optional[list[str]] = Field(
        default=None,
        description="List of datasites whose jobs will be automatically approved.",
    )


class DatasetCreate(ItemBaseCreate[Dataset]):
    name: str = Field(description="Name of the dataset.")
    path: str = Field(description="Private path of the dataset.")
    mock_path: str = Field(description="Mock path of the dataset.")
    summary: Optional[str] = Field(description="Summary string of the dataset.")
    description_path: Optional[str] = Field(
        description="Path to the detailed REAMD.md of the dataset."
    )
    tags: Optional[list[str]] = Field(description="Tags for the dataset.")
    runtime_id: Optional[UUID] = Field(
        default=None, description="ID of the default runtime for the dataset."
    )
    auto_approval: list[str] = Field(
        default_factory=list,
        description="List of datasites whose jobs will be automatically approved.",
    )
