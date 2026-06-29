from pydantic import BaseModel, Field


class ServicePeriod(BaseModel):
    """A group of services representing a schedule period."""

    name: str
    service_ids: list[str] = Field(default_factory=list)
    description: str = ""
