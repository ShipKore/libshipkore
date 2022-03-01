"""Main module."""
import os
import time
from .track import get_track_data  # noqa
from .track import get_providers  # noqa

os.environ["TZ"] = "UTC"
time.tzset()
