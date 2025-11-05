JOB_STATUS_POLLING_INTERVAL = 2
SYFTBOX_DATASITES_BASE_URL = "https://syftbox.net/datasites"


def get_datasite_url(email: str) -> str:
    """Generate a SyftBox datasite URL for a given email."""
    return f"{SYFTBOX_DATASITES_BASE_URL}/{email}"
