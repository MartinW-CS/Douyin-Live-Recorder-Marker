from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from douyin_live_marker.events import LiveEvent


class EventCollector(ABC):
    @abstractmethod
    def collect(self) -> AsyncIterator[LiveEvent]:
        """Yield normalized live events from an external source."""
