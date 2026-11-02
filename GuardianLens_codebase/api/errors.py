# The one error type the API raises on purpose. The handler registered in main.py turns it into
# the API's standard error body (`{"error": {code, message, field}}`).
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AppError(Exception):
    """A deliberate API error: HTTP status, stable code, plain message, and the field it concerns.

    `message` is safe to show to a buyer, and `field` names the form field the error belongs to
    (None when it is not about one field).
    """

    status_code: int
    code: str
    message: str
    field: str | None = None
