from datetime import date, datetime
from typing import List, Optional, Union
from pydantic import BaseModel
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


class Checkpoint(BaseModel):
    slug: str
    city: Optional[str]
    location: Optional[str]
    country_name: Optional[str]
    message: Optional[str]
    submessage: Optional[str]
    country_iso3: Optional[str]
    status: StatusChoice = StatusChoice.Exception
    substatus: Optional[str]
    checkpoint_time: Union[datetime, date]
    state: Optional[str]
    zip: Optional[str]


class Track(BaseModel):
    checkpoints: List[Checkpoint]

    waybill: str
    provider: str
    status: StatusChoice = StatusChoice.Exception
    substatus: Optional[str]
    estimated_date: Optional[Union[datetime, date]]
    reference_no: Optional[str]
    package_type: Optional[str]
    destination: Optional[str]
    client: Optional[str]
    consignee_address: Optional[str]
    product: Optional[str]
    receiver_name: Optional[str]
    delivered_date: Optional[Union[datetime, date]]
