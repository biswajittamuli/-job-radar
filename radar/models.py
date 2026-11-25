from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class RawJob:
    """A job exactly as one ATS reported it, normalised to common fields."""
    source_id: str
    title: str
    url: str
    locations: list[str] = field(default_factory=list)
    posted_at: str | None = None        # ISO-8601 date if the ATS gives one
    description: str = ""               # plain text, may be empty
    remote: bool | None = None
    team: str = ""
    level_hint: str = ""                # the ATS's own experience level, if it states one


@dataclass
class Job:
    """A job that passed the filters, as stored in data/jobs.json."""
    id: str
    company: str
    title: str
    url: str
    location: str
    level: str                  # intern | entry | open
    skills: list[str]
    score: int
    posted_at: str | None
    first_seen: str
    last_seen: str
    status: str = "open"        # open | closed
    closed_at: str | None = None
    years: int | None = None    # min years of experience asked, if stated
    remote: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def newest_first(posted_at: str | None, score: int) -> tuple:
    """Sort key: newest posting date first, undated jobs after dated ones, then best score.
    Use with sorted(..., key=...) in ascending order."""
    d = (posted_at or "")[:10]
    # invert the ISO date so ascending order means newest first
    inv = tuple(-ord(ch) for ch in d)
    return (0 if d else 1, inv, -score)
