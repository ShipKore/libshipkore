class ShipkoreError(Exception):
    pass


class CredentialsError(ShipkoreError):
    """A required credential was not supplied."""


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
