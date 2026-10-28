from datetime import date, time
from typing import Dict, List, Optional
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
    PickupReschedule = "PickupReschedule"


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
    # None means the provider did not say, not that the mode is unsupported
    prepaid: Optional[bool]
    cod: Optional[bool]
    pickup: Optional[bool]
    remark: Optional[str]


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
    # the provider's own id when later calls need it, e.g. a pickup request
    reference: Optional[str]
    remarks: List[str] = []


class Label(BaseModel):
    provider: str
    waybill: str
    url: Optional[str]
    content: Optional[bytes]
    content_type: str = "application/pdf"
    # signed links lapse; download or regenerate before this many seconds
    expires_in: Optional[int]


class Cancellation(BaseModel):
    provider: str
    waybill: str
    status: RequestStatus
    message: Optional[str]


class PickupRequest(BaseModel):
    """
    Carriers book pickups per warehouse (Delhivery: warehouse, time and
    package_count) or per shipment (Shiprocket: shipment_ids).
    """

    pickup_date: date
    warehouse: Optional[str]
    pickup_time: Optional[time]
    package_count: Optional[int]
    shipment_ids: List[str] = []


class Pickup(BaseModel):
    provider: str
    pickup_id: str
    warehouse: Optional[str]
    # the provider may assign a different slot than the one requested
    pickup_date: date
    pickup_time: Optional[time]
    package_count: Optional[int]
    center: Optional[str]


class NdrRequest(BaseModel):
    waybill: str
    action: NdrAction
    deferred_date: Optional[date]
    name: Optional[str]
    phone: Optional[str]
    address: Optional[str]


class NdrResult(BaseModel):
    provider: str
    waybill: Optional[str]
    request_id: str
    status: RequestStatus = RequestStatus.Pending
    message: Optional[str]
    # a batch can partly succeed, so check these and not only status
    succeeded: List[str] = []
    failed: Dict[str, str] = {}
