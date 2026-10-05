class DomainError(Exception):
    """Business-rule violation. The API layer turns it into an HTTP response."""

    def __init__(self, code: str, message: str, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def not_found(what: str) -> DomainError:
    return DomainError("NOT_FOUND", f"{what} not found", 404)
