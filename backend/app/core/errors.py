"""Application errors and unified API error rendering."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AppError(Exception):
    """Expected application failure with a stable public error code.

    ``details`` is optional and additive. It carries structured context for errors
    that have more to say than a single message, such as the field-level issues of
    a configuration validation failure. Errors without details render exactly as
    before.
    """

    code: str
    message: str
    status_code: int
    details: dict[str, Any] = field(default_factory=dict)
