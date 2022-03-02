"""Main module."""
import os
import time
from libshipkore.track import get_track_data  # noqa
from libshipkore.track import get_providers  # noqa

os.environ["TZ"] = "UTC"
time.tzset()
