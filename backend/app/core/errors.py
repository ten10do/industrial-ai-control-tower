"""Application errors and unified API error rendering."""

from dataclasses import dataclass


@dataclass(slots=True)
class AppError(Exception):
    """Expected application failure with a stable public error code."""

    code: str
    message: str
    status_code: int
