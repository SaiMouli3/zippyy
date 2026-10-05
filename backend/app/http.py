import httpx


def make_client(base_url: str, timeout: float = 5.0) -> httpx.AsyncClient:
    """Single place HTTP clients are built. Tests swap this to route calls in-process."""
    return httpx.AsyncClient(base_url=base_url, timeout=timeout)
