import re
from datetime import datetime, timedelta, timezone

import parsel
import requests

from libshipkore.common.exceptions import ProviderError
from ..common.basetrackservice import BaseTrackService, track_registry
from ..models.model import StatusChoice

IST = timezone(timedelta(hours=5, minutes=30))
SCAN_TIME = re.compile(r"^\d\d/\d\d/\d{4} \d\d:\d\d$")


def squash(text):
    return " ".join(text.split())


@track_registry.register("trackon")
class TrackOn(BaseTrackService):
    """
    Trackon Couriers. POST https://trackon.in/courier-tracking with the field
    awbSingleTrackingId and a trackon.in Referer answers with an HTML page
    (no captcha, no cookie); the scans are the rows of its table, newest
    first. Without the Referer, or for a number Trackon has no record of, the
    page comes back with no table. Seen 2026-10-29 for one delivered
    consignment (tests/fixtures/trackon_courier_tracking.html, hand-redacted):
    the words below that appear there are DELIVERED, UNDELIVERED DUE TO ... and
    IN TRANSIT TO; the rest (booked, processing, arrived, out for delivery)
    come from the old scraper and are unverified. Times are day/month/year,
    taken as Indian Standard Time.
    """

    def status_mapper(self, status):
        status = status.upper()
        if "UNDELIVERED" in status:  # before DELIVERED, which it contains
            return StatusChoice.AttemptFail
        elif status.startswith("S/MENT BOOKED"):
            return StatusChoice.InfoReceived
        elif status.startswith("PROCESSING"):
            return StatusChoice.InTransit
        elif status.startswith("S/MENT ARRIVED"):
            return StatusChoice.InTransit
        elif status.startswith("IN TRANSIT"):
            return StatusChoice.InTransit
        elif status.startswith("OUT FOR DELIVERY"):
            return StatusChoice.OutForDelivery
        elif "DELIVERED" in status:
            return StatusChoice.Delivered
        else:
            return StatusChoice.Exception

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, "trackon", *args, **kwargs)

    def _fetch(self):
        response = requests.post(
            "https://trackon.in/courier-tracking",
            headers={"Referer": "https://trackon.in/"},
            data={"awbSingleTrackingId": self.waybill},
            timeout=30,
        )
        if not response.ok:
            raise ProviderError(
                self.provider,
                f"HTTP {response.status_code}",
                status_code=response.status_code,
                body=response.text,
            )
        self.raw_data = response.text

    def _transform(self):
        selector = parsel.Selector(text=self.raw_data)
        checkpoints = []
        for row in selector.xpath("//table//tr[td]"):
            cells = row.xpath("./td")
            if len(cells) < 5:
                continue
            when = squash("".join(cells[0].xpath(".//text()").getall()))
            if not SCAN_TIME.match(when):
                continue
            event = squash("".join(cells[4].xpath(".//text()").getall()))
            location = squash("".join(cells[2].xpath(".//text()").getall()))
            checkpoints.append({
                "slug": self.provider,
                "location": location or None,
                "country_name": "India",
                "country_iso3": "IND",
                "message": event,
                "status": self.status_mapper(event),
                "substatus": event,
                "checkpoint_time": datetime.strptime(when, "%d/%m/%Y %H:%M").replace(tzinfo=IST),
            })
        if not checkpoints:
            raise ProviderError(
                self.provider,
                f"no tracking record for {self.waybill} (the number is wrong, "
                "or too old for Trackon to show)",
                body=self.raw_data[:500],
            )
        checkpoints.sort(key=lambda c: c["checkpoint_time"], reverse=True)

        due = re.search(r"DueDate\s*:\s*(\d\d/\d\d/\d{4})", selector.get() or "")
        newest = checkpoints[0]
        self.data = {
            "waybill": self.waybill,
            "provider": self.provider,
            "status": newest["status"],
            "substatus": newest["substatus"],
            "estimated_date": (
                datetime.strptime(due.group(1), "%d/%m/%Y").replace(tzinfo=IST) if due else None
            ),
            "delivered_date": (
                newest["checkpoint_time"] if newest["status"] == StatusChoice.Delivered else None
            ),
            "checkpoints": checkpoints,
        }
