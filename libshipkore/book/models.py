from datetime import date, datetime, time
from typing import Dict, List, Optional
from pydantic import Field
from libshipkore.common.models import Model
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


class Address(Model):
    name: str
    phone: str
    address: str
    pincode: str
    city: Optional[str] = None
    state: Optional[str] = None
    country: str = "India"
    email: Optional[str] = None


class Parcel(Model):
    weight_kg: float
    length_cm: Optional[float] = None
    breadth_cm: Optional[float] = None
    height_cm: Optional[float] = None


class ShipmentRequest(Model):
    order_id: str
    consignee: Address
    pickup_location: str
    parcel: Parcel
    payment_mode: PaymentMode = PaymentMode.Prepaid
    cod_amount: float = 0
    declared_value: float = 0
    description: Optional[str] = None
    quantity: int = 1
    waybill: Optional[str] = None
    is_reverse: bool = False
    invoice_number: Optional[str] = None
    e_waybill: Optional[str] = None


class ServiceabilityResult(Model):
    provider: str
    pincode: str
    serviceable: bool
    # None means the provider did not say, not that the mode is unsupported
    prepaid: Optional[bool] = None
    cod: Optional[bool] = None
    pickup: Optional[bool] = None
    remark: Optional[str] = None


class Rate(Model):
    provider: str
    amount: float
    currency: str = "INR"
    service: Optional[str] = None
    estimated_days: Optional[int] = None


class Shipment(Model):
    provider: str
    waybill: str
    order_id: str
    status: str
    # the provider's own id when later calls need it, e.g. a pickup request
    reference: Optional[str] = None
    remarks: List[str] = []


class Label(Model):
    provider: str
    waybill: str
    url: Optional[str] = None
    content: Optional[bytes] = Field(default=None, exclude=True)
    content_type: str = "application/pdf"
    # signed links lapse; download or regenerate before this many seconds
    expires_in: Optional[int] = None
    # set when a copy of the PDF is kept in the file store
    storage_key: Optional[str] = None


class Cancellation(Model):
    provider: str
    waybill: str
    status: RequestStatus
    message: Optional[str] = None


class PickupRequest(Model):
    """
    Carriers book pickups per warehouse (Delhivery: warehouse, time and
    package_count) or per shipment (Shiprocket: shipment_ids).
    """

    pickup_date: date
    warehouse: Optional[str] = None
    pickup_time: Optional[time] = None
    package_count: Optional[int] = None
    shipment_ids: List[str] = []


class Pickup(Model):
    provider: str
    pickup_id: str
    warehouse: Optional[str] = None
    # the provider may assign a different slot than the one requested
    pickup_date: date
    pickup_time: Optional[time] = None
    package_count: Optional[int] = None
    center: Optional[str] = None


class NdrRequest(Model):
    waybill: str
    action: NdrAction
    deferred_date: Optional[date] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None


class NdrResult(Model):
    provider: str
    waybill: Optional[str] = None
    request_id: str
    status: RequestStatus = RequestStatus.Pending
    message: Optional[str] = None
    # a batch can partly succeed, so check these and not only status
    succeeded: List[str] = []
    failed: Dict[str, str] = {}


class ServiceType(Model):
    """A service level a provider offers, such as Express or Surface."""

    provider: str
    code: str
    name: str
    mode: Optional[str] = None


class Product(Model):
    """A catalog entry that orders refer to by sku."""

    sku: str
    name: str
    price: float
    weight_kg: float
    description: Optional[str] = None
    hsn: Optional[str] = None
    tax_percent: Optional[float] = None
    length_cm: Optional[float] = None
    breadth_cm: Optional[float] = None
    height_cm: Optional[float] = None


class OrderItem(Model):
    sku: str
    quantity: int = 1


class OrderStatus(str, enum.Enum):
    Failed = "Failed"
    Booked = "Booked"
    CancelPending = "CancelPending"
    Cancelled = "Cancelled"


class Order(Model):
    order_id: str
    provider: str
    status: OrderStatus
    consignee: Address
    pickup_location: str
    parcel: Parcel
    payment_mode: PaymentMode = PaymentMode.Prepaid
    cod_amount: float = 0
    declared_value: float = 0
    items: List[OrderItem] = []
    description: Optional[str] = None
    invoice_number: Optional[str] = None
    waybill: Optional[str] = None
    reference: Optional[str] = None
    error: Optional[str] = None
    # latest tracking status, set when the order is tracked
    delivery_status: Optional[str] = None
    pickup: Optional[Pickup] = None
    ndr: List[NdrResult] = []
    created_at: datetime
    updated_at: datetime
