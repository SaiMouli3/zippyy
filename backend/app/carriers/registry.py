from app.carriers.base import CarrierAdapter
from app.carriers.fastship import FastShipAdapter
from app.carriers.quickexpress import QuickExpressAdapter
from app.carriers.reliable import ReliableCourierAdapter

# Adding a 4th carrier = write an adapter + add it here.
_ADAPTERS: list[CarrierAdapter] = [FastShipAdapter(), QuickExpressAdapter(), ReliableCourierAdapter()]


def all_adapters() -> list[CarrierAdapter]:
    return list(_ADAPTERS)


def get_adapter(carrier_code: str) -> CarrierAdapter:
    for a in _ADAPTERS:
        if a.code == carrier_code.upper():
            return a
    raise KeyError(carrier_code)


def get_adapter_by_slug(slug: str) -> CarrierAdapter:
    for a in _ADAPTERS:
        if a.webhook_slug == slug:
            return a
    raise KeyError(slug)
