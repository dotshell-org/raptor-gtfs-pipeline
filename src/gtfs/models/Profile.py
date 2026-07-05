from pydantic import BaseModel, Field


class PeriodRule(BaseModel):
    """Rule assigning services to a target period.

    A service matches when it satisfies **all** provided conditions:
      - ``days``: the service runs on at least one of these days. Tokens are
        ``mon``..``sun``, ranges like ``mon-fri``, and aliases ``weekdays`` /
        ``weekend`` / ``daily``.
      - ``service_id_matches``: a regex searched against the ``service_id``.
    An empty rule (no conditions) matches every service.
    """

    days: list[str] = Field(default_factory=list)
    service_id_matches: str | None = None
    description: str = ""


class Profile(BaseModel):
    """Declarative period profile (loaded from YAML).

    ``periods`` maps a target folder name to its :class:`PeriodRule`. A service
    may match several periods (e.g. a daily service belongs to both weekday and
    weekend periods). ``unmatched`` decides what happens to services matched by
    no rule: ``other`` buckets them into an ``other`` folder, ``warn`` logs and
    drops them.
    """

    network: str = ""
    periods: dict[str, PeriodRule]
    unmatched: str = "other"
