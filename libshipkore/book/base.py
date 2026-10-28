import logging
import requests
from class_registry import ClassRegistry
from libshipkore.common.baseservice import BaseService
from libshipkore.common.exceptions import ProviderError, UnsupportedOperation
from libshipkore.track import get_track_data, track_registry

carrier_registry = ClassRegistry()
logger = logging.getLogger(__name__)

OPERATIONS = (
    "track",
    "serviceability",
    "services",
    "rates",
    "create_shipment",
    "label",
    "cancel",
    "schedule_pickup",
    "ndr_action",
    "ndr_status",
)


class BaseCarrier(BaseService):
    """
    The one interface every provider offers, whatever it can actually do.
    A carrier overrides only the operations its API has; the rest raise
    UnsupportedOperation, and `capabilities` reports the difference so
    callers can check before calling.

    Unlike the track services there is no single run() pipeline: each
    operation is its own method.
    """

    provider = None
    base_url = None
    sandbox_url = None

    def __init__(self, credentials=None, sandbox=False, session=None, timeout=30):
        super().__init__(credentials=credentials)
        self.sandbox = sandbox
        self.session = session or requests.Session()
        self.timeout = timeout
        # called with (provider, method, path, status_code, body) after
        # every API call, for audit logging; failures here never propagate
        self.recorder = None

    @property
    def capabilities(self):
        """Names of the operations this provider supports."""
        supported = {
            op for op in OPERATIONS
            if op != "track"
            and getattr(type(self), op) is not getattr(BaseCarrier, op)
        }
        if self.provider in track_registry.keys():
            supported.add("track")
        return supported

    @property
    def root(self):
        if self.sandbox:
            if not self.sandbox_url:
                raise UnsupportedOperation(f"{self.provider}: no sandbox")
            return self.sandbox_url
        return self.base_url

    def _headers(self):
        return {}

    def _request(self, method, path, **kwargs):
        headers = {**self._headers(), **kwargs.pop("headers", {})}
        response = self.session.request(
            method,
            self.root + path,
            headers=headers,
            timeout=self.timeout,
            **kwargs,
        )
        self._record(method, path, response)
        if not response.ok:
            raise ProviderError(
                self.provider,
                f"HTTP {response.status_code} on {path}",
                status_code=response.status_code,
                body=response.text,
            )
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            raise ProviderError(
                self.provider,
                f"non-JSON response on {path}",
                status_code=response.status_code,
                body=response.text,
            )

    def _record(self, method, path, response):
        if self.recorder is None:
            return
        try:
            self.recorder(
                self.provider, method, path, response.status_code, response.text
            )
        except Exception:
            logger.exception("response recorder failed")

    def _unsupported(self, operation):
        raise UnsupportedOperation(f"{self.provider}: {operation}")

    def track(self, waybill):
        """Tracking goes through the shared tracker registry."""
        if self.provider not in track_registry.keys():
            self._unsupported("track")
        return get_track_data(self.provider, waybill)

    def serviceability(self, pincode, origin_pincode=None):
        """origin_pincode is for carriers that price or gate by lane."""
        self._unsupported("serviceability")

    def services(self):
        """The service levels (Express, Surface...) this provider offers."""
        self._unsupported("services")

    def rates(self, origin_pincode, destination_pincode, parcel,
              payment_mode, cod_amount=0):
        self._unsupported("rates")

    def create_shipment(self, request):
        self._unsupported("create_shipment")

    def label(self, waybill, reference=None, size=None):
        """
        reference is the Shipment.reference from create_shipment, for
        providers that key labels on their own id. size is "A4" or "4R"
        where the provider lets the caller choose.
        """
        self._unsupported("label")

    def cancel(self, waybill):
        self._unsupported("cancel")

    def schedule_pickup(self, request):
        self._unsupported("schedule_pickup")

    def ndr_action(self, request):
        self._unsupported("ndr_action")

    def ndr_status(self, request_id):
        self._unsupported("ndr_status")


class TrackOnlyCarrier(BaseCarrier):
    """A provider the library can only track, through the same interface."""

    def __init__(self, provider, **kwargs):
        super().__init__(**kwargs)
        self.provider = provider
