import re
from datetime import date, datetime
from typing import Annotated, Union

from pydantic import BaseModel, BeforeValidator, ConfigDict, PlainSerializer

DATE_ONLY = re.compile(r"\d{4}-\d{2}-\d{2}")


class Model(BaseModel):
    """
    Base for every library model. Trackers and carriers hand over values
    straight from scraped pages and JSON, where a zip code or phone number
    arrives as a number as often as a string, so numbers are accepted for
    string fields (pydantic 1 did this implicitly; pydantic 2 does not).
    """

    model_config = ConfigDict(coerce_numbers_to_str=True)


def _keep_date_only(value):
    if isinstance(value, str) and DATE_ONLY.fullmatch(value.strip()):
        return date.fromisoformat(value.strip())
    return value


# A moment or a calendar day, as tracking data gives either. These keep the
# pydantic 1 behaviour that existing output depends on: a date-only string
# stays a date (pydantic 2 would make it midnight), and JSON output is plain
# isoformat, so UTC reads +00:00 and not Z.
DateOrDateTime = Annotated[
    Union[datetime, date],
    BeforeValidator(_keep_date_only),
    PlainSerializer(lambda value: value.isoformat(), return_type=str,
                    when_used="json"),
]
