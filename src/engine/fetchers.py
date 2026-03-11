from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.engine.models import QueryOutcome, QuerySpec
from src.frontier_client import FrontierClient


class Fetcher(Protocol):
    def fetch(self, spec: QuerySpec) -> QueryOutcome: ...


@dataclass
class RequestsFrontierFetcher:
    client: FrontierClient

    def fetch(self, spec: QuerySpec) -> QueryOutcome:
        return self.client.search_outcome(spec)

