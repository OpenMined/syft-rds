import shutil
from pathlib import Path
from typing_extensions import Final, Type
from uuid import UUID

from syft_rds.client.local_stores.base import CRUDLocalStore
from syft_rds.models import Job, JobCreate, JobUpdate


class JobLocalStore(CRUDLocalStore[Job, JobCreate, JobUpdate]):
    ITEM_TYPE: Final[Type[Job]] = Job

    def share_result_files(self, job: Job, job_output_folder: Path) -> Path:
        """
        Share the results with the user by moving the output files from the job output folder (local filesystem)
        to the output folder on SyftBox.
        """

        syftbox_output_path = job.output_url.to_local_path(
            self.syftbox_client.datasites
        )
        if not syftbox_output_path.exists():
            syftbox_output_path.mkdir(parents=True)

        # Copy all contents from job_output_folder to the output path
        for item in job_output_folder.iterdir():
            if item.is_file():
                shutil.copy2(item, syftbox_output_path)
            elif item.is_dir():
                shutil.copytree(
                    item,
                    syftbox_output_path / item.name,
                    dirs_exist_ok=True,
                )

        return syftbox_output_path

    def delete_by_id(self, uid: UUID) -> bool:
        """Delete a job by its UUID.

        Args:
            uid: UUID of the job to delete

        Returns:
            True if the job was deleted, False if not found
        """
        return self.store.delete(uid)
