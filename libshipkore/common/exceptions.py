class ShipkoreError(Exception):
    pass


class CredentialsError(ShipkoreError):
    """A required credential was not supplied."""


class ConfirmationError(ShipkoreError):
    """A confirmation token is missing, unknown, expired, used, or for other arguments."""


class ConfigError(ShipkoreError):
    """The configuration file or its environment variables are invalid."""


class StorageError(ShipkoreError):
    """The database or file storage failed or is misconfigured."""


class NotFound(ShipkoreError):
    """An order, product or stored file does not exist."""


class DuplicateOrder(ShipkoreError):
    """An order with this id was already booked."""


class UnknownProvider(ShipkoreError):
    """No tracker or carrier is registered under this name."""


class UnsupportedOperation(ShipkoreError):
    """The provider does not offer this operation."""


class ProviderError(ShipkoreError):
    """The provider rejected the request or returned an unusable response."""

    def __init__(self, provider, message, status_code=None, body=None):
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.status_code = status_code
        self.body = body
