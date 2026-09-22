"""Abstract contract implemented by industrial protocol adapters."""

from abc import ABC, abstractmethod

from adapters.models import AdapterHealth, ProtocolType, UnifiedTelemetry


class IndustrialProtocolAdapter(ABC):
    """Protocol boundary that produces normalized telemetry."""

    @property
    @abstractmethod
    def protocol(self) -> ProtocolType:
        """Return the protocol represented by this adapter."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish the underlying protocol connection."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the underlying protocol connection."""

    @abstractmethod
    async def read(self) -> UnifiedTelemetry:
        """Read and normalize one telemetry sample."""

    @abstractmethod
    def health(self) -> AdapterHealth:
        """Return the adapter's current health snapshot."""
