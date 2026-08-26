"""Application time helpers.

MySQL DATETIME values are stored without timezone metadata, so the application
normalizes every generated timestamp to Beijing time before persisting it.
"""

from datetime import datetime
from zoneinfo import ZoneInfo


BEIJING_TZ = ZoneInfo("Asia/Shanghai")


def beijing_now() -> datetime:
    """Return the current Beijing time as a naive datetime for MySQL DATETIME."""
    return datetime.now(BEIJING_TZ).replace(tzinfo=None)
