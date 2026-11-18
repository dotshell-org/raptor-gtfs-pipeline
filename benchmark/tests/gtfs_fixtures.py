"""Tiny GTFS feeds built in memory, for tests that must not touch the network or real data."""

from __future__ import annotations

import io
import zipfile

MINIMAL_FEED = {
    "agency.txt": "agency_id,agency_name,agency_url,agency_timezone\nA,Test,https://example.org,Europe/Paris\n",
    "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\nS1,Gare,45.75,4.85\nS2,Mairie,45.76,4.86\n",
    "routes.txt": "route_id,agency_id,route_short_name,route_type\nR1,A,1,3\n",
    "trips.txt": "route_id,service_id,trip_id\nR1,WK,T1\n",
    "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                      "T1,08:00:00,08:00:00,S1,1\nT1,08:10:00,08:10:00,S2,2\n",
    "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
                    "WK,1,1,1,1,1,0,0,20261102,20261218\n",
    "calendar_dates.txt": "service_id,date,exception_type\nWK,20261219,1\nWK,20261111,2\n",
}


def zip_bytes(files: dict[str, str | bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def feed_zip(prefix: str = "", files: dict[str, str] | None = None) -> bytes:
    return zip_bytes({prefix + name: content for name, content in (files or MINIMAL_FEED).items()})
