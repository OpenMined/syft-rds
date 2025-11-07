from pathlib import Path
from typing import Union
from syft_core import SyftBoxURL

from syft_rds.client.local_stores.dataset.constants import (
    DIRECTORY_DATASETS,
    DIRECTORY_PRIVATE_DATASETS,
    DIRECTORY_PRIVATE_DATASETS_ROOT,
    DIRECTORY_PUBLIC,
)


class DatasetUrlManager:
    """Manages SyftBox URLs for datasets."""

    @staticmethod
    def get_mock_dataset_syftbox_url(
        datasite_email: str, dataset_name: str, mock_path: Union[Path, str] = None
    ) -> SyftBoxURL:
        """Generate a SyftBox URL for the mock dataset."""
        return SyftBoxURL(
            f"syft://{datasite_email}/{DIRECTORY_PUBLIC}/{DIRECTORY_DATASETS}/{dataset_name}"
        )

    @staticmethod
    def get_private_dataset_syftbox_url(
        datasite_email: str, dataset_name: str, path: Union[Path, str] = None
    ) -> SyftBoxURL:
        """Generate SyftBox URL for private dataset.

        NOTE: This URL is for local access only. Since private datasets are
        stored outside the datasites folder, they are NOT accessible remotely
        through the SyftBox relay server.

        Args:
            datasite_email: Owner's email address
            dataset_name: Name of the dataset
            path: Optional path within the dataset

        Returns:
            SyftBoxURL pointing to private dataset location
        """
        url_path = (
            f"{DIRECTORY_PRIVATE_DATASETS_ROOT}/{DIRECTORY_PRIVATE_DATASETS}/"
            f"{datasite_email}/{dataset_name}"
        )

        if path:
            url_path = f"{url_path}/{path}"

        return SyftBoxURL(f"syft://{datasite_email}/{url_path}")

    @staticmethod
    def get_readme_syftbox_url(
        datasite_email: str, dataset_name: str, readme_path: Union[Path, str]
    ) -> SyftBoxURL:
        """Generate a SyftBox URL for the readme file."""
        return SyftBoxURL(
            f"syft://{datasite_email}/{DIRECTORY_PUBLIC}/{DIRECTORY_DATASETS}/{dataset_name}/{Path(readme_path).name}"
        )

    @staticmethod
    def update_readme_syftbox_url(
        url: SyftBoxURL, *, dataset_name: str = None
    ) -> SyftBoxURL:
        path = Path(url.path)
        datasite_email = url.host

        if dataset_name:
            path = path.parent.parent / dataset_name / path.name

        return SyftBoxURL(f"syft://{datasite_email}/{path}")
