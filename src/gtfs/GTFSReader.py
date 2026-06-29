import csv
import logging
from pathlib import Path
from typing import Any

from src.gtfs.models.Agency import Agency
from src.gtfs.models.Calendar import Calendar
from src.gtfs.models.CalendarDate import CalendarDate
from src.gtfs.models.Route import Route
from src.gtfs.models.Stop import Stop
from src.gtfs.models.StopTime import StopTime
from src.gtfs.models.Transfer import Transfer
from src.gtfs.models.Trip import Trip

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

    def _read_rows(self, filename: str, required: bool = True) -> list[dict[str, str]]:
        """Read rows from a GTFS CSV file, returning empty list if optional and missing."""
        file_path = self.gtfs_path / filename
        if not file_path.exists():
            if required:
                raise FileNotFoundError(f"Required file not found: {file_path}")
            return []
        with open(file_path) as f:
            reader = csv.DictReader(f)
            return list(reader)

    def _create_mapping(
        self,
        raw_list: list[tuple[str, Any]],
        id_map: dict[str, int],
        internal_to_id: dict[int, str],
        target_list: list[Any],
    ) -> None:
        """Sort raw list and populate internal mappings."""
        raw_list.sort(key=lambda x: x[0])
        for idx, (gtfs_id, item) in enumerate(raw_list):
            id_map[gtfs_id] = idx
            internal_to_id[idx] = gtfs_id
            target_list.append(item)

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
        rows = self._read_rows("agencies.txt", required=False)
        if not rows:
            rows = self._read_rows("agency.txt", required=False)
            if not rows:
                logger.warning("agencies.txt not found, skipping")
                return

        for row in rows:
            agency = Agency(
                agency_id=row.get("agency_id", ""),
                agency_name=row["agency_name"],
                agency_timezone=row["agency_timezone"],
            )
            self.agencies.append(agency)

    def read_calendar(self) -> None:
        """Read calendar.txt."""
        rows = self._read_rows("calendar.txt", required=False)
        if not rows:
            logger.info("calendar.txt not found, skipping")
            return

        for row in rows:
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
        rows = self._read_rows("calendar_dates.txt", required=False)
        if not rows:
            logger.info("calendar_dates.txt not found, skipping")
            return

        for row in rows:
            exception_type_str = row.get("exception_type", "").strip()
            if not exception_type_str:
                logger.warning(
                    f"Service {row['service_id']} on {row['date']} "
                    "has empty exception_type, skipping"
                )
                continue
            try:
                exception_type = int(exception_type_str)
            except ValueError:
                logger.warning(
                    f"Service {row['service_id']} on {row['date']} has "
                    f"invalid exception_type '{exception_type_str}', skipping"
                )
                continue
            
            calendar_date = CalendarDate(
                service_id=row["service_id"],
                date=row["date"],
                exception_type=exception_type,
            )
            self.calendar_dates.append(calendar_date)

    def read_stops(self) -> None:
        """Read stops.txt and create internal ID mapping."""
        stops_raw: list[tuple[str, Stop]] = []
        for row in self._read_rows("stops.txt"):
            stop_id = row["stop_id"]
            name = row.get("stop_name", "")
            
            try:
                lat = float(row.get("stop_lat", "").strip())
                lon = float(row.get("stop_lon", "").strip())
            except (ValueError, AttributeError):
                logger.warning(f"Stop {stop_id} has invalid coordinates, skipping")
                continue
            
            stop = Stop(stop_id=stop_id, name=name, lat=lat, lon=lon)
            stops_raw.append((stop_id, stop))

        self._create_mapping(stops_raw, self.stop_id_map, self.internal_to_stop, self.stops)

    def read_routes(self) -> None:
        """Read routes.txt and create internal ID mapping."""
        routes_raw: list[tuple[str, Route]] = []
        for row in self._read_rows("routes.txt"):
            route_id = row["route_id"]
            
            route_type_str = row.get("route_type", "").strip()
            if not route_type_str:
                logger.warning(f"Route {route_id} has empty route_type, using default (3=bus)")
                route_type = 3
            else:
                try:
                    route_type = int(route_type_str)
                except ValueError:
                    logger.warning(
                        f"Route {route_id} has invalid route_type "
                        f"'{route_type_str}', using default (3=bus)"
                    )
                    route_type = 3
            
            route = Route(
                route_id=route_id,
                route_short_name=row.get("route_short_name", ""),
                route_long_name=row.get("route_long_name", ""),
                route_type=route_type,
            )
            routes_raw.append((route_id, route))

        self._create_mapping(routes_raw, self.route_id_map, self.internal_to_route, self.routes)

    def read_trips(self) -> None:
        """Read trips.txt and create internal ID mapping."""
        trips_raw: list[tuple[str, Trip]] = []
        for row in self._read_rows("trips.txt"):
            trip_id = row["trip_id"]
            
            direction_id_str = row.get("direction_id", "0").strip()
            if not direction_id_str:
                direction_id = 0
            else:
                try:
                    direction_id = int(direction_id_str)
                except ValueError:
                    logger.warning(
                        f"Trip {trip_id} has invalid direction_id "
                        f"'{direction_id_str}', using 0"
                    )
                    direction_id = 0
            
            trip = Trip(
                trip_id=trip_id,
                route_id=row["route_id"],
                service_id=row["service_id"],
                direction_id=direction_id,
            )
            trips_raw.append((trip_id, trip))

        self._create_mapping(trips_raw, self.trip_id_map, self.internal_to_trip, self.trips)

    def read_stop_times(self) -> None:
        """Read stop_times.txt and normalize times."""
        stop_times_raw: list[StopTime] = []
        for row in self._read_rows("stop_times.txt"):
            trip_id = row["trip_id"]
            stop_id = row["stop_id"]
            
            try:
                arrival_time = self._parse_time(row.get("arrival_time", ""))
                departure_time = self._parse_time(row.get("departure_time", ""))
            except ValueError as e:
                logger.warning(f"Trip {trip_id} stop {stop_id} has invalid times: {e}, skipping")
                continue
            
            stop_sequence_str = row.get("stop_sequence", "").strip()
            if not stop_sequence_str:
                logger.warning(f"Trip {trip_id} stop {stop_id} has empty stop_sequence, skipping")
                continue
            try:
                stop_sequence = int(stop_sequence_str)
            except ValueError:
                logger.warning(
                    f"Trip {trip_id} stop {stop_id} has invalid "
                    f"stop_sequence '{stop_sequence_str}', skipping"
                )
                continue

            stop_time = StopTime(
                trip_id=trip_id,
                stop_id=stop_id,
                arrival_time=arrival_time,
                departure_time=departure_time,
                stop_sequence=stop_sequence,
            )
            stop_times_raw.append(stop_time)

        stop_times_raw.sort(key=lambda st: (st.trip_id, st.stop_sequence))
        self.stop_times = stop_times_raw

    def read_transfers(self) -> None:
        """Read transfers.txt if present."""
        rows = self._read_rows("transfers.txt", required=False)
        if not rows:
            logger.info("transfers.txt not found, no explicit transfers")
            return

        for row in rows:
            from_stop = row["from_stop_id"]
            to_stop = row["to_stop_id"]
            
            min_time_str = row.get("min_transfer_time", "0").strip()
            if not min_time_str:
                min_time = 0
            else:
                try:
                    min_time = int(min_time_str)
                except ValueError:
                    logger.warning(
                        f"Transfer {from_stop}->{to_stop} has invalid "
                        f"min_transfer_time '{min_time_str}', using 0"
                    )
                    min_time = 0

            transfer = Transfer(
                from_stop_id=from_stop,
                to_stop_id=to_stop,
                min_transfer_time=min_time,
            )
            self.transfers.append(transfer)

    @staticmethod
    def _parse_time(time_str: str) -> int:
        """Parse HH:MM:SS to seconds since midnight, supporting >24h."""
        time_str = time_str.strip()
        if not time_str:
            raise ValueError("Empty time string")
        
        parts = time_str.split(":")
        if len(parts) != 3:
            raise ValueError(f"Invalid time format: {time_str}")

        try:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = int(parts[2])
        except ValueError:
            raise ValueError(f"Invalid time format: {time_str}")

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
