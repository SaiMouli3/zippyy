from fastapi.encoders import jsonable_encoder


def _camel(k: str) -> str:
    head, *rest = k.split("_")
    return head + "".join(p.capitalize() for p in rest)


def camelize(o):
    if isinstance(o, dict):
        return {_camel(k) if isinstance(k, str) else k: camelize(v) for k, v in o.items()}
    if isinstance(o, list):
        return [camelize(v) for v in o]
    return o


def out(data):
    """Serialise service results: JSON-safe, camelCase keys."""
    return camelize(jsonable_encoder(data))


class ApiError(Exception):
    def __init__(self, status: int, message: str, **extra):
        self.status, self.message, self.extra = status, message, extra
