from datetime import date, time
from typing import List, Optional
from pydantic import BaseModel
import enum


class PaymentMode(str, enum.Enum):
    Prepaid = "Prepaid"
    COD = "COD"


class RequestStatus(str, enum.Enum):
    """State of an operation the provider may complete asynchronously."""

    Accepted = "Accepted"
    Pending = "Pending"
    Completed = "Completed"
    Failed = "Failed"


class NdrAction(str, enum.Enum):
    Reattempt = "Reattempt"
    Defer = "Defer"
    EditDetails = "EditDetails"


class Address(BaseModel):
    name: str
    phone: str
    address: str
    pincode: str
    city: Optional[str]
    state: Optional[str]
    country: str = "India"
    email: Optional[str]


class Parcel(BaseModel):
    weight_kg: float
    length_cm: Optional[float]
    breadth_cm: Optional[float]
    height_cm: Optional[float]


class ShipmentRequest(BaseModel):
    order_id: str
    consignee: Address
    pickup_location: str
    parcel: Parcel
    payment_mode: PaymentMode = PaymentMode.Prepaid
    cod_amount: float = 0
    declared_value: float = 0
    description: Optional[str]
    quantity: int = 1
    waybill: Optional[str]
    is_reverse: bool = False
    invoice_number: Optional[str]
    e_waybill: Optional[str]


class ServiceabilityResult(BaseModel):
    provider: str
    pincode: str
    serviceable: bool
    prepaid: bool = False
    cod: bool = False
    pickup: bool = False


class Rate(BaseModel):
    provider: str
    amount: float
    currency: str = "INR"
    service: Optional[str]
    estimated_days: Optional[int]


class Shipment(BaseModel):
    provider: str
    waybill: str
    order_id: str
    status: str
    remarks: List[str] = []


class Cancellation(BaseModel):
    provider: str
    waybill: str
    status: RequestStatus
    message: Optional[str]


class PickupRequest(BaseModel):
    warehouse: str
    pickup_date: date
    pickup_time: time
    package_count: int


class Pickup(BaseModel):
    provider: str
    pickup_id: str
    warehouse: str
    pickup_date: date
    pickup_time: time
    package_count: int


class NdrRequest(BaseModel):
    waybill: str
    action: NdrAction
    deferred_date: Optional[date]
    name: Optional[str]
    phone: Optional[str]
    address: Optional[str]


class NdrResult(BaseModel):
    provider: str
    waybill: str
    request_id: str
    status: RequestStatus = RequestStatus.Pending
    message: Optional[str]
