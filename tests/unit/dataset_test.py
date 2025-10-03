import pandas as pd
import pytest
from syft_rds.client.rds_client import RDSClient
from tests.conftest import MOCK_DATA_PATH, PRIVATE_DATA_PATH, README_PATH
from tests.utils import create_dataset


def test_create_dataset(do_rds_client: RDSClient) -> None:
    assert do_rds_client.is_admin

    dataset = create_dataset(do_rds_client, "Test")
    assert dataset.name == "Test"
    assert dataset.get_mock_path().exists()
    assert dataset.get_private_path().exists()
    assert dataset.summary == "Test data"
    assert dataset.describe() is None  # Check if describe works
    private_df = pd.read_csv(dataset.get_private_path() / "data.csv")
    assert private_df.equals(pd.read_csv(PRIVATE_DATA_PATH / "data.csv"))
    mock_df = pd.read_csv(dataset.get_mock_path() / "data.csv")
    assert mock_df.equals(pd.read_csv(MOCK_DATA_PATH / "data.csv"))


def test_get_dataset(do_rds_client: RDSClient) -> None:
    assert do_rds_client.is_admin

    dataset = create_dataset(do_rds_client, "Test")
    test_data = do_rds_client.dataset.get(name="Test")
    assert test_data.name == dataset.name
    assert test_data.get_mock_path().exists()
    assert test_data.get_private_path().exists()
    assert test_data.summary == dataset.summary
    private_df = pd.read_csv(test_data.get_private_path() / "data.csv")
    assert private_df.equals(pd.read_csv(PRIVATE_DATA_PATH / "data.csv"))
    mock_df = pd.read_csv(test_data.get_mock_path() / "data.csv")
    assert mock_df.equals(pd.read_csv(MOCK_DATA_PATH / "data.csv"))


def test_get_all_datasets(do_rds_client: RDSClient) -> None:
    assert do_rds_client.is_admin

    dataset_1 = create_dataset(do_rds_client, "Test")
    datasets = do_rds_client.dataset.get_all()
    assert len(datasets) == 1

    dataset_2 = create_dataset(do_rds_client, "Test 2")
    datasets = do_rds_client.dataset.get_all()
    assert len(datasets) == 2

    assert dataset_1 in datasets
    assert dataset_2 in datasets


def test_delete_dataset(do_rds_client: RDSClient) -> None:
    """Test deleting a dataset and verifying it's removed from storage and filesystem."""
    assert do_rds_client.is_admin

    # Create a dataset to delete
    dataset = create_dataset(do_rds_client, "TestToDelete")

    # Verify it exists
    mock_path = dataset.get_mock_path()
    private_path = dataset.get_private_path()
    assert mock_path.exists()
    assert private_path.exists()

    # Get all datasets before deletion
    datasets_before = do_rds_client.dataset.get_all()
    assert any(d.name == "TestToDelete" for d in datasets_before)

    # Delete the dataset
    success = do_rds_client.dataset.delete("TestToDelete")
    assert success is True

    # Verify it's gone from the list
    datasets_after = do_rds_client.dataset.get_all()
    assert not any(d.name == "TestToDelete" for d in datasets_after)
    assert len(datasets_after) == len(datasets_before) - 1

    # Try to get the deleted dataset (should raise an error)
    with pytest.raises(ValueError, match="No Dataset found with"):
        do_rds_client.dataset.get(name="TestToDelete")

    # Verify files are cleaned up (should no longer exist)
    assert not mock_path.parent.exists() or not any(mock_path.parent.iterdir())
    assert not private_path.parent.exists() or not any(private_path.parent.iterdir())


def test_delete_nonexistent_dataset(do_rds_client: RDSClient) -> None:
    """Test deleting a dataset that doesn't exist returns False."""
    assert do_rds_client.is_admin

    # Try to delete a non-existent dataset
    success = do_rds_client.dataset.delete("NonExistentDataset")
    assert success is False


def test_permission_error_non_admin(
    do_rds_client: RDSClient, ds_rds_client: RDSClient
) -> None:
    """Test that non-admin users cannot create or delete datasets."""
    assert do_rds_client.is_admin
    assert not ds_rds_client.is_admin

    # Attempt to create a dataset as non-admin
    with pytest.raises(PermissionError, match="You must be the datasite admin"):
        create_dataset(ds_rds_client, "TestPermissionError")

    # Create a dataset as admin first
    dataset = create_dataset(do_rds_client, "TestPermissionError")

    # Then try to delete it as non-admin
    with pytest.raises(PermissionError, match="You must be the datasite admin"):
        ds_rds_client.dataset.delete(dataset.name)


def test_create_datasets_same_name(do_rds_client: RDSClient) -> None:
    """Test that creating a dataset with an existing name raises an error."""
    assert do_rds_client.is_admin

    # Create a dataset
    create_dataset(do_rds_client, "DuplicateName")

    with pytest.raises(
        ValueError, match="Dataset with name 'DuplicateName' already exists"
    ):
        create_dataset(do_rds_client, "DuplicateName")


def test_readme_content(do_rds_client: RDSClient) -> None:
    """Test that README content is correctly stored and retrieved."""
    assert do_rds_client.is_admin

    # Create a dataset with a README
    dataset = create_dataset(do_rds_client, "TestReadme")

    # Retrieve the dataset and check README content
    retrieved = do_rds_client.dataset.get(name=dataset.name)

    # Assuming we've implemented the get_description method
    readme_content = retrieved.get_description()
    assert readme_content is not None
    assert len(readme_content) > 0

    # Compare with the original file
    with open(README_PATH, "r") as f:
        original_content = f.read()

    assert readme_content == original_content


def test_permission_error_private_path_access(
    do_rds_client: RDSClient, ds_rds_client: RDSClient
) -> None:
    """Test that non-admin users cannot access private paths even when dataset exists."""
    assert do_rds_client.is_admin
    assert not ds_rds_client.is_admin

    # Create a dataset as admin
    create_dataset(do_rds_client, "TestPrivateAccess")

    # Get the same dataset through the non-admin client
    non_admin_dataset = ds_rds_client.dataset.get(name="TestPrivateAccess")

    # Non-admin should be able to access mock path
    mock_path = non_admin_dataset.get_mock_path()
    assert mock_path.exists()

    # But should get PermissionError when trying to access private path
    with pytest.raises(
        PermissionError, match="You must be the datasite admin to access private data"
    ):
        non_admin_dataset.get_private_path()

    # Also test the property access
    with pytest.raises(
        PermissionError, match="You must be the datasite admin to access private data"
    ):
        _ = non_admin_dataset.private_path

    # Admin dataset
    admin_dataset = do_rds_client.dataset.get(name="TestPrivateAccess")
    assert admin_dataset.get_mock_path().exists()
    assert admin_dataset.get_private_path().exists()
