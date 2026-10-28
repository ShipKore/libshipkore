from typing import List, Optional
from libshipkore.common.models import DateOrDateTime, Model
import enum


class StatusChoice(str, enum.Enum):
    InfoReceived = "InfoReceived"
    InTransit = "InTransit"
    OutForDelivery = "OutForDelivery"
    AttemptFail = "AttemptFail"
    Delivered = "Delivered"
    AvailableForPickup = "AvailableForPickup"
    Exception = "Exception"
    ReverseDelivered = "ReverseDelivered"
    ReverseOutForDelivery = "ReverseOutForDelivery"
    ReverseInTransit = "ReverseInTransit"


class Checkpoint(Model):
    slug: str
    city: Optional[str] = None
    location: Optional[str] = None
    country_name: Optional[str] = None
    message: Optional[str] = None
    submessage: Optional[str] = None
    country_iso3: Optional[str] = None
    status: StatusChoice = StatusChoice.Exception
    substatus: Optional[str] = None
    checkpoint_time: DateOrDateTime
    state: Optional[str] = None
    zip: Optional[str] = None


class Track(Model):
    checkpoints: List[Checkpoint]

    waybill: str
    provider: str
    status: StatusChoice = StatusChoice.Exception
    substatus: Optional[str] = None
    estimated_date: Optional[DateOrDateTime] = None
    reference_no: Optional[str] = None
    package_type: Optional[str] = None
    destination: Optional[str] = None
    client: Optional[str] = None
    consignee_address: Optional[str] = None
    product: Optional[str] = None
    receiver_name: Optional[str] = None
    delivered_date: Optional[DateOrDateTime] = None
