from loguru import logger
import os
from pathlib import Path

from syft_rds.client.rds_clients.base import RDSClientModule
from syft_rds.client.rds_clients.utils import ensure_is_admin
from syft_rds.models import (
    Runtime,
    RuntimeCreate,
    RuntimeKind,
    RuntimeConfig,
    PythonRuntimeConfig,
    DockerRuntimeConfig,
    KubernetesRuntimeConfig,
)

DEFAULT_RUNTIME_KIND = os.getenv("SYFT_RDS_DEFAULT_RUNTIME_KIND", "python")
DEFAULT_RUNTIME_NAME = os.getenv(
    "SYFT_RDS_DEFAULT_RUNTIME_NAME", "syft_default_python_runtime"
)
PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DOCKERFILE_FILE_PATH = PROJECT_ROOT / "runtimes" / "python.Dockerfile"


class RuntimeRDSClient(RDSClientModule[Runtime]):
    ITEM_TYPE = Runtime

    @ensure_is_admin
    def create(
        self,
        runtime_name: str,
        runtime_kind: str,
        config: dict | None = None,
        description: str | None = None,
    ) -> Runtime:
        """Create a runtime. Only admins can create runtimes."""

        # Validate runtime kind
        valid_kinds = [r.value for r in RuntimeKind]
        if runtime_kind not in valid_kinds:
            raise ValueError(
                f"Invalid runtime kind: {runtime_kind}. Must be one of {valid_kinds}"
            )

        # Check for duplicates
        existing = self.get_runtime_by_name(runtime_name)
        if existing:
            raise ValueError(f"Runtime '{runtime_name}' already exists")

        # Create runtime config and runtime
        runtime_config = self._create_runtime_config(runtime_kind, config)
        runtime_create = RuntimeCreate(
            name=runtime_name,
            kind=RuntimeKind(runtime_kind),
            config=runtime_config,
            description=description,
        )

        runtime = self.rpc.runtime.create(runtime_create)
        logger.info(f"Runtime created: {runtime}")
        return runtime

    def get_runtime_by_name(self, name: str) -> Runtime | None:
        try:
            return self.get(name=name)
        except Exception as e:
            logger.debug(f"Error getting runtime by name: {e}")
            return None

    def _create_runtime_config(
        self, runtime_kind: str, config: dict | None = None
    ) -> RuntimeConfig:
        if config is None:
            config = {}

        kind_str = runtime_kind.lower()

        config_map = {
            RuntimeKind.PYTHON.value: PythonRuntimeConfig,
            RuntimeKind.DOCKER.value: DockerRuntimeConfig,
            RuntimeKind.KUBERNETES.value: KubernetesRuntimeConfig,
        }

        config_class = config_map.get(kind_str)

        if config_class:
            return config_class(**config)
        else:
            raise ValueError(f"Unsupported runtime type: {runtime_kind}")
