"""Collector: one implementation per data source. Justified as an interface
because there are, and will keep being, many independent, unstable
implementations (see CLAUDE.md rule #5) -- this is the strongest case for an
ABC anywhere in this project.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from typing import ClassVar

from opportunity_engine.domain.models import RawDocument


@dataclass(frozen=True)
class ConnectorManifest:
    """Developer-maintained source of truth for what a connector is, its
    quota, and its ToS status -- mirrored into the `connectors` table (via
    `tools.storage.upsert_connector_manifest`) purely for operational
    visibility, not as a second live source of truth for enable/disable
    (that's `Settings.disabled_connectors`, read once in `registry.py`)."""

    name: str
    source_description: str
    source_url: str
    quota_description: str
    tos_url: str
    tos_status: str  # 'compliant' | 'review_needed' | 'unknown'
    last_verified: date
    requires_auth: bool = False


class Collector(ABC):
    manifest: ClassVar[ConnectorManifest]

    @abstractmethod
    def collect(self, since: datetime, until: datetime) -> Iterator[RawDocument]:
        """Yield RawDocuments published/observed in [since, until).

        Must not raise on a single malformed item -- log and skip it. May
        raise on a whole-connector failure (auth, network, quota exhaustion);
        callers (IngestionAgent) catch that per-connector and continue with
        the others.
        """
        raise NotImplementedError
