from libshipkore.common.exceptions import ProviderError
from libshipkore.track.common.basetrackservice import BaseTrackService

ORDER = ("api", "request", "browser")


class LayeredTracker(BaseTrackService):
    """
    A tracker that may know several ways to get the data and tries them in the
    order of preference: the courier's API, then a direct request to a public
    endpoint, then the page in a browser. Define `fetch_api`, `fetch_request`
    and/or `fetch_browser`; each returns the raw data or raises. The first
    that works wins and is named in `self.strategy`.

    `transform_<strategy>` turns that strategy's raw data into the Track
    data; without one, `transform` is used for all.
    """

    strategy = None

    def _fetch(self):
        failures = []
        for name in ORDER:
            fetch = getattr(self, f"fetch_{name}", None)
            if fetch is None:
                continue
            try:
                self.raw_data = fetch()
            except Exception as error:  # the next layer may still work
                failures.append(f"{name}: {type(error).__name__}: {error}")
                continue
            self.strategy = name
            return
        if not failures:
            raise NotImplementedError(f"{type(self).__name__} defines no fetch_* method")
        raise ProviderError(
            self.provider, f"no way of tracking {self.waybill} worked ({'; '.join(failures)})"
        )

    def _transform(self):
        transform = getattr(self, f"transform_{self.strategy}", None) or self.transform
        return transform()

    def transform(self):
        raise NotImplementedError
