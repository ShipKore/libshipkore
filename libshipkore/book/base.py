import requests
from class_registry import ClassRegistry
from libshipkore.common.baseservice import BaseService
from libshipkore.common.exceptions import ProviderError, UnsupportedOperation

carrier_registry = ClassRegistry()


class BaseCarrier(BaseService):
    """
    A provider client for the shipment lifecycle. Unlike the track services
    there is no single run() pipeline: each operation is its own method, and
    a carrier overrides only the ones its API offers.
    """

    provider = None
    base_url = None
    sandbox_url = None

    def __init__(self, credentials=None, sandbox=False, session=None, timeout=30):
        super().__init__(credentials=credentials)
        self.sandbox = sandbox
        self.session = session or requests.Session()
        self.timeout = timeout

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

    def _unsupported(self, operation):
        raise UnsupportedOperation(f"{self.provider}: {operation}")

    def serviceability(self, pincode, origin_pincode=None):
        """origin_pincode is for carriers that price or gate by lane."""
        self._unsupported("serviceability")

    def rates(self, origin_pincode, destination_pincode, parcel,
              payment_mode, cod_amount=0):
        self._unsupported("rates")

    def create_shipment(self, request):
        self._unsupported("create_shipment")

    def cancel(self, waybill):
        self._unsupported("cancel")

    def schedule_pickup(self, request):
        self._unsupported("schedule_pickup")

    def ndr_action(self, request):
        self._unsupported("ndr_action")

    def ndr_status(self, request_id):
        self._unsupported("ndr_status")
