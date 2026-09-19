"""Shared provider-adapter values and hygienic errors."""

from __future__ import annotations

from dataclasses import dataclass


class AdapterError(RuntimeError):
    """A provider call failed without exposing credentials or unbounded response data."""

    def __init__(
        self,
        provider: str,
        *,
        status: int | None = None,
        where: str = "",
        detail: str = "",
    ) -> None:
        self.provider = provider
        self.status = status
        self.where = where
        self.detail = detail

        parts = [provider]
        if where:
            parts.append(where)
        parts.append("failed")
        if status is not None:
            parts[-1] = f"failed ({status})"
        message = " ".join(parts)
        if detail:
            message += f": {detail[:200]}"
        super().__init__(message)


@dataclass(frozen=True)
class Cost:
    """The cost amount returned by an adapter and how it was determined."""

    amount: float
    source: str
