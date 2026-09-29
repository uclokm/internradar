from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class RawJob:
    """A posting as a source returns it, before any interpretation."""
    source: str                 # greenhouse | workday | workable | internsg | manual
    external_id: str
    company: str
    title: str
    url: str
    location: str = ""
    department: str = ""
    posted: date | None = None
    period_text: str = ""       # the most date-like snippet the source exposes (e.g. InternSG "Job Period")
    description: str = ""       # plain text

    @property
    def key(self) -> str:
        return f"{self.source}:{self.external_id}"


@dataclass
class Job:
    """A posting after classification, ready to store and show."""
    key: str
    source: str
    company: str
    title: str
    url: str
    location: str
    posted: date | None
    dates: str                  # human-readable period, e.g. "Dec 2026 – May 2027"
    start: date | None
    end: date | None
    min_months: float | None
    tier: str                   # T1 | T2 | ?  ("?" = dates unclear, needs a look)
    fit: str                    # strong | stretch | weak | unclear
    family: str                 # INV | AM | DATA | OPS | STRAT (drives the tailored CV)
    area: str                   # human label for the family
    note: str
    description: str = ""
    extra: dict = field(default_factory=dict)
