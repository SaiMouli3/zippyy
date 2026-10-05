from .base import CarrierAdapter
from .fastship import FastShipAdapter
from .quickexpress import QuickExpressAdapter
from .reliable import ReliableCourierAdapter

ADAPTERS: list[CarrierAdapter] = [FastShipAdapter(), QuickExpressAdapter(), ReliableCourierAdapter()]
BY_CODE = {a.code: a for a in ADAPTERS}
BY_SLUG = {a.slug: a for a in ADAPTERS}
