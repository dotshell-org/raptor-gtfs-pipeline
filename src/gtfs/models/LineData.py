from pydantic import BaseModel, Field


class LinePath(BaseModel):
    """A single directional polyline of a transit line.

    ``points`` are ordered ``(lon, lat)`` pairs (GeoJSON axis order).
    """

    direction_id: int
    points: list[tuple[float, float]] = Field(default_factory=list)


class LineData(BaseModel):
    """Geometry of a transit line, derived from GTFS ``shapes.txt``.

    One :class:`LinePath` per direction (the longest shape of that direction).
    ``transport_type`` is the raw GTFS ``route_type`` — the consumer maps it to
    its own taxonomy. ``color``/``text_color`` are GTFS hex values without ``#``
    (possibly empty).
    """

    line_id_internal: int
    name: str
    transport_type: int
    color: str = ""
    text_color: str = ""
    paths: list[LinePath] = Field(default_factory=list)
