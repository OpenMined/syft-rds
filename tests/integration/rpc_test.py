from pathlib import Path

import pytest
from syft_core import Client as SyftBoxClient
from syft_core import SyftClientConfig
from syft_event import SyftEvents
from syft_rds.client.rds_client import init_session
from syft_rds.orchestra import RDSStack
from syft_rds.server.app import create_app

DO_EMAIL = "data_owner@test.openmined.org"
DS_EMAIL = "data_scientist@test.openmined.org"

# NOTE: for testing real RPC and file sharing without launching the full stack, we use a shared data dir.
SHARED_DATA_DIR = "shared_data_dir"


@pytest.fixture
def do_syftbox_client(tmp_path: Path) -> SyftBoxClient:
    return SyftBoxClient(
        SyftClientConfig(
            email=DO_EMAIL,
            client_url="http://localhost:5000",
            path=tmp_path / "syftbox_client_config.json",
            data_dir=tmp_path / "clients" / SHARED_DATA_DIR,
        ),
    )


@pytest.fixture
def ds_syftbox_client(tmp_path: Path) -> SyftBoxClient:
    return SyftBoxClient(
        SyftClientConfig(
            email=DS_EMAIL,
            client_url="http://localhost:5001",
            path=tmp_path / "syftbox_client_config.json",
            data_dir=tmp_path / "clients" / SHARED_DATA_DIR,
        ),
    )


@pytest.fixture
def rds_server(do_syftbox_client: SyftBoxClient):
    return create_app(do_syftbox_client)


def test_rpc_mocked(rds_server: SyftEvents, ds_syftbox_client):
    ds_rds_client = init_session(
        host=DO_EMAIL, syftbox_client=ds_syftbox_client, mock_server=rds_server
    )
    do_rds_client = init_session(
        host=DO_EMAIL, syftbox_client=ds_syftbox_client, mock_server=rds_server
    )

    info = ds_rds_client.rpc.health()
    assert info["app_name"] == "RDS"

    info = do_rds_client.rpc.health()
    assert info["app_name"] == "RDS"


def test_rpc_with_files(rds_no_sync_stack: RDSStack):
    do_rds_client = rds_no_sync_stack.do_rds_client
    ds_rds_client = rds_no_sync_stack.ds_rds_client

    info = ds_rds_client.rpc.health()
    assert info["app_name"] == "RDS"

    info = do_rds_client.rpc.health()
    assert info["app_name"] == "RDS"
