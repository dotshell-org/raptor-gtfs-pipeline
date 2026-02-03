"""GTFS data reader and normalizer."""

import csv
import logging
from pathlib import Path

from raptor_pipeline.gtfs.models import Agency, Calendar, CalendarDate, Route, Stop, StopTime, Transfer, Trip

logger = logging.getLogger(__name__)


class GTFSReader:
    """Read and normalize GTFS feed from directory."""

    def __init__(self, gtfs_path: str) -> None:
        """Initialize reader with GTFS directory path."""
        self.gtfs_path = Path(gtfs_path)
        if not self.gtfs_path.is_dir():
            raise ValueError(f"GTFS path not found or not a directory: {gtfs_path}")

        # ID mappings: GTFS string -> internal uint32
        self.stop_id_map: dict[str, int] = {}
        self.route_id_map: dict[str, int] = {}
        self.trip_id_map: dict[str, int] = {}

        # Reverse mappings
        self.internal_to_stop: dict[int, str] = {}
        self.internal_to_route: dict[int, str] = {}
        self.internal_to_trip: dict[int, str] = {}

        # Data storage
        self.stops: list[Stop] = []
        self.routes: list[Route] = []
        self.trips: list[Trip] = []
        self.stop_times: list[StopTime] = []
        self.transfers: list[Transfer] = []
        self.agencies: list[Agency] = []
        self.calendar: list[Calendar] = []
        self.calendar_dates: list[CalendarDate] = []

    def read_all(self) -> None:
        """Read all GTFS files."""
        logger.info(f"Reading GTFS data from {self.gtfs_path}")
        self.read_agencies()
        self.read_stops()
        self.read_routes()
        self.read_calendar()
        self.read_calendar_dates()
        self.read_trips()
        self.read_stop_times()
        self.read_transfers()
        logger.info(
            f"Loaded {len(self.stops)} stops, {len(self.routes)} routes, "
            f"{len(self.trips)} trips, {len(self.stop_times)} stop_times, "
            f"{len(self.transfers)} transfers, {len(self.calendar)} calendar entries, "
            f"{len(self.calendar_dates)} calendar date exceptions"
        )

    def read_agencies(self) -> None:
        """Read agencies.txt."""
        file_path = self.gtfs_path / "agencies.txt"
        if not file_path.exists():
            # Try agency.txt as fallback
            file_path = self.gtfs_path / "agency.txt"
            if not file_path.exists():
                logger.warning("agencies.txt not found, skipping")
                return

        with open(file_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                agency = Agency(
                    agency_id=row.get("agency_id", ""),
                    agency_name=row["agency_name"],
                    agency_timezone=row["agency_timezone"],
                )
                self.agencies.append(agency)

    def read_calendar(self) -> None:
        """Read calendar.txt."""
        file_path = self.gtfs_path / "calendar.txt"
        if not file_path.exists():
            logger.info("calendar.txt not found, skipping")
            return

        with open(file_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                calendar = Calendar(
                    service_id=row["service_id"],
                    monday=row["monday"] == "1",
                    tuesday=row["tuesday"] == "1",
                    wednesday=row["wednesday"] == "1",
                    thursday=row["thursday"] == "1",
                    friday=row["friday"] == "1",
                    saturday=row["saturday"] == "1",
                    sunday=row["sunday"] == "1",
                    start_date=row["start_date"],
                    end_date=row["end_date"],
                )
                self.calendar.append(calendar)

    def read_calendar_dates(self) -> None:
        """Read calendar_dates.txt."""
        file_path = self.gtfs_path / "calendar_dates.txt"
        if not file_path.exists():
            logger.info("calendar_dates.txt not found, skipping")
            return

        with open(file_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                calendar_date = CalendarDate(
                    service_id=row["service_id"],
                    date=row["date"],
                    exception_type=int(row["exception_type"]),
                )
                self.calendar_dates.append(calendar_date)

    def read_stops(self) -> None:
        """Read stops.txt and create internal ID mapping."""
        file_path = self.gtfs_path / "stops.txt"
        if not file_path.exists():
            raise FileNotFoundError(f"Required file not found: {file_path}")

        stops_raw: list[tuple[str, Stop]] = []
        with open(file_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                stop_id = row["stop_id"]
                name = row.get("stop_name", "")
                lat = float(row["stop_lat"])
                lon = float(row["stop_lon"])
                stop = Stop(stop_id=stop_id, name=name, lat=lat, lon=lon)
                stops_raw.append((stop_id, stop))

        # Sort by stop_id for stable mapping
        stops_raw.sort(key=lambda x: x[0])

        for idx, (stop_id, stop) in enumerate(stops_raw):
            internal_id = idx
            self.stop_id_map[stop_id] = internal_id
            self.internal_to_stop[internal_id] = stop_id
            self.stops.append(stop)

    def read_routes(self) -> None:
        """Read routes.txt and create internal ID mapping."""
        file_path = self.gtfs_path / "routes.txt"
        if not file_path.exists():
            raise FileNotFoundError(f"Required file not found: {file_path}")

        routes_raw: list[tuple[str, Route]] = []
        with open(file_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                route_id = row["route_id"]
                route = Route(
                    route_id=route_id,
                    route_short_name=row.get("route_short_name", ""),
                    route_long_name=row.get("route_long_name", ""),
                    route_type=int(row["route_type"]),
                )
                routes_raw.append((route_id, route))

        # Sort by route_id for stable mapping
        routes_raw.sort(key=lambda x: x[0])

        for idx, (route_id, route) in enumerate(routes_raw):
            internal_id = idx
            self.route_id_map[route_id] = internal_id
            self.internal_to_route[internal_id] = route_id
            self.routes.append(route)

    def read_trips(self) -> None:
        """Read trips.txt and create internal ID mapping."""
        file_path = self.gtfs_path / "trips.txt"
        if not file_path.exists():
            raise FileNotFoundError(f"Required file not found: {file_path}")

        trips_raw: list[tuple[str, Trip]] = []
        with open(file_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                trip_id = row["trip_id"]
                direction_id = int(row.get("direction_id", "0"))
                trip = Trip(
                    trip_id=trip_id,
                    route_id=row["route_id"],
                    service_id=row["service_id"],
                    direction_id=direction_id,
                )
                trips_raw.append((trip_id, trip))

        # Sort by trip_id for stable mapping
        trips_raw.sort(key=lambda x: x[0])

        for idx, (trip_id, trip) in enumerate(trips_raw):
            internal_id = idx
            self.trip_id_map[trip_id] = internal_id
            self.internal_to_trip[internal_id] = trip_id
            self.trips.append(trip)

    def read_stop_times(self) -> None:
        """Read stop_times.txt and normalize times."""
        file_path = self.gtfs_path / "stop_times.txt"
        if not file_path.exists():
            raise FileNotFoundError(f"Required file not found: {file_path}")

        stop_times_raw: list[StopTime] = []
        with open(file_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                trip_id = row["trip_id"]
                stop_id = row["stop_id"]
                arrival_time = self._parse_time(row["arrival_time"])
                departure_time = self._parse_time(row["departure_time"])
                stop_sequence = int(row["stop_sequence"])

                stop_time = StopTime(
                    trip_id=trip_id,
                    stop_id=stop_id,
                    arrival_time=arrival_time,
                    departure_time=departure_time,
                    stop_sequence=stop_sequence,
                )
                stop_times_raw.append(stop_time)

        # Sort by trip_id, then stop_sequence for normalization
        stop_times_raw.sort(key=lambda st: (st.trip_id, st.stop_sequence))
        self.stop_times = stop_times_raw

    def read_transfers(self) -> None:
        """Read transfers.txt if present."""
        file_path = self.gtfs_path / "transfers.txt"
        if not file_path.exists():
            logger.info("transfers.txt not found, no explicit transfers")
            return

        with open(file_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                from_stop = row["from_stop_id"]
                to_stop = row["to_stop_id"]
                min_time = int(row.get("min_transfer_time", "0"))

                transfer = Transfer(
                    from_stop_id=from_stop,
                    to_stop_id=to_stop,
                    min_transfer_time=min_time,
                )
                self.transfers.append(transfer)

    @staticmethod
    def _parse_time(time_str: str) -> int:
        """Parse HH:MM:SS to seconds since midnight, supporting >24h."""
        parts = time_str.strip().split(":")
        if len(parts) != 3:
            raise ValueError(f"Invalid time format: {time_str}")

        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2])

        return hours * 3600 + minutes * 60 + seconds

    def get_internal_stop_id(self, gtfs_stop_id: str) -> int:
        """Get internal stop ID from GTFS stop ID."""
        return self.stop_id_map[gtfs_stop_id]

    def get_internal_route_id(self, gtfs_route_id: str) -> int:
        """Get internal route ID from GTFS route ID."""
        return self.route_id_map[gtfs_route_id]

    def get_internal_trip_id(self, gtfs_trip_id: str) -> int:
        """Get internal trip ID from GTFS trip ID."""
        return self.trip_id_map[gtfs_trip_id]
