"""Integration tests for private dataset path structure (v0.5.0)."""

from syft_core import SyftClientConfig
from syft_rds.client.rds_client import RDSClient, init_session
from tests.utils import create_dataset


def test_private_dataset_stored_outside_datasites(
    do_syftbox_config: SyftClientConfig,
) -> None:
    """Verify private datasets are stored outside the datasites folder."""
    do_rds_client: RDSClient = init_session(
        host=do_syftbox_config.email,
        email=do_syftbox_config.email,
        syftbox_client_config_path=do_syftbox_config.path,
        start_syft_event_server=False,
    )
    assert do_rds_client.is_admin

    # Create a dataset
    dataset = create_dataset(do_rds_client, "PathTestDataset")

    # Get the private path
    private_path = dataset.get_private_path()

    # Verify it's in .syftbox/private_datasets, NOT in datasites
    assert ".syftbox" in str(private_path)
    assert "private_datasets" in str(private_path)
    assert "datasites" not in str(private_path)
    assert private_path.exists()

    # Verify the actual directory structure
    # Expected: ~/.syftbox/private_datasets/<email>/<dataset-name>/
    path_parts = private_path.parts
    assert ".syftbox" in path_parts
    assert "private_datasets" in path_parts
    assert do_syftbox_config.email in path_parts
    assert "PathTestDataset" in path_parts


def test_private_and_mock_paths_separated(
    do_syftbox_config: SyftClientConfig,
) -> None:
    """Verify private and mock datasets are in completely separate locations."""
    do_rds_client: RDSClient = init_session(
        host=do_syftbox_config.email,
        email=do_syftbox_config.email,
        syftbox_client_config_path=do_syftbox_config.path,
        start_syft_event_server=False,
    )
    assert do_rds_client.is_admin

    dataset = create_dataset(do_rds_client, "SeparationTest")

    private_path = dataset.get_private_path()
    mock_path = dataset.get_mock_path()

    # Paths should be completely different
    assert private_path != mock_path
    assert private_path.parent != mock_path.parent

    # Mock should be in datasites folder (synced)
    assert "datasites" in str(mock_path)
    assert "public" in str(mock_path)
    assert "datasets" in str(mock_path)

    # Private should be outside datasites (not synced)
    assert "datasites" not in str(private_path)
    assert ".syftbox/private_datasets" in str(private_path)

    # Both should exist
    assert private_path.exists()
    assert mock_path.exists()


def test_private_dataset_url_format(do_syftbox_config: SyftClientConfig) -> None:
    """Verify private and mock dataset URLs have correct format."""
    do_rds_client: RDSClient = init_session(
        host=do_syftbox_config.email,
        email=do_syftbox_config.email,
        syftbox_client_config_path=do_syftbox_config.path,
        start_syft_event_server=False,
    )
    assert do_rds_client.is_admin

    dataset = create_dataset(do_rds_client, "URLTest")

    # Check private URL format
    private_url = str(dataset.private)
    assert f"syft://{do_syftbox_config.email}" in private_url
    assert ".syftbox/private_datasets" in private_url
    assert f"{do_syftbox_config.email}/URLTest" in private_url

    # Check mock URL format
    mock_url = str(dataset.mock)
    assert f"syft://{do_syftbox_config.email}" in mock_url
    assert "public/datasets/URLTest" in mock_url
    # Should NOT have extra path segments
    assert "/private/" not in mock_url


def test_multi_user_private_path_isolation(
    do_syftbox_config: SyftClientConfig, ds_syftbox_config: SyftClientConfig
) -> None:
    """Verify different users get isolated private dataset directories."""
    # Create DO client
    do_rds_client: RDSClient = init_session(
        host=do_syftbox_config.email,
        email=do_syftbox_config.email,
        syftbox_client_config_path=do_syftbox_config.path,
        start_syft_event_server=False,
    )
    assert do_rds_client.is_admin

    # Create DS client (simulating a second data owner on same machine)
    ds_rds_client: RDSClient = init_session(
        host=ds_syftbox_config.email,
        email=ds_syftbox_config.email,
        syftbox_client_config_path=ds_syftbox_config.path,
        start_syft_event_server=False,
    )
    assert ds_rds_client.is_admin

    # Both create datasets with same name
    do_dataset = create_dataset(do_rds_client, "SharedName")
    ds_dataset = create_dataset(ds_rds_client, "SharedName")

    # Get private paths
    do_private_path = do_dataset.get_private_path()
    ds_private_path = ds_dataset.get_private_path()

    # Paths should be different
    assert do_private_path != ds_private_path

    # Each should contain their respective email
    assert do_syftbox_config.email in str(do_private_path)
    assert ds_syftbox_config.email in str(ds_private_path)

    # Both should exist
    assert do_private_path.exists()
    assert ds_private_path.exists()

    # Verify data doesn't overlap
    assert do_private_path.parent != ds_private_path.parent
