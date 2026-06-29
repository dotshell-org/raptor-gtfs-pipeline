import logging
from pathlib import Path

import numpy as np
import pandas as pd

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
    """Read and normalize GTFS feed from directory using vectorized Pandas operations."""

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

        # Pydantic model lists (kept for downstream compatibility)
        self.stops: list[Stop] = []
        self.routes: list[Route] = []
        self.trips: list[Trip] = []
        self.stop_times: list[StopTime] = []  # Deprecated — use stop_times_df
        self.transfers: list[Transfer] = []
        self.agencies: list[Agency] = []
        self.calendar: list[Calendar] = []
        self.calendar_dates: list[CalendarDate] = []

        # High-performance DataFrames for bulk operations
        self.stop_times_df: pd.DataFrame = pd.DataFrame()
        self.trips_df: pd.DataFrame = pd.DataFrame()

    # ------------------------------------------------------------------
    # Core I/O
    # ------------------------------------------------------------------

    def _read_df(self, filename: str, required: bool = True) -> pd.DataFrame:
        """Read a GTFS CSV file as a DataFrame. Returns empty DF if optional and missing."""
        file_path = self.gtfs_path / filename
        if not file_path.exists():
            if required:
                raise FileNotFoundError(f"Required file not found: {file_path}")
            return pd.DataFrame()
        return pd.read_csv(file_path, dtype=str, na_filter=False, low_memory=False)

    @staticmethod
    def _parse_time_series(series: pd.Series) -> pd.Series:  # type: ignore[type-arg]
        """Vectorized HH:MM:SS → seconds since midnight (supports HH > 24)."""
        s = series.str.strip()
        empty = s.eq("")
        parts = s.str.split(":", expand=True)
        if parts.shape[1] < 3:
            return pd.Series([np.nan] * len(series), dtype="float64")
        hours = pd.to_numeric(parts[0], errors="coerce")
        minutes = pd.to_numeric(parts[1], errors="coerce")
        seconds = pd.to_numeric(parts[2], errors="coerce")
        result = hours * 3600 + minutes * 60 + seconds
        result[empty] = np.nan
        return result  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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
            f"{len(self.trips)} trips, {len(self.stop_times_df)} stop_times, "
            f"{len(self.transfers)} transfers, {len(self.calendar)} calendar entries, "
            f"{len(self.calendar_dates)} calendar date exceptions"
        )

    # ------------------------------------------------------------------
    # Loaders
    # ------------------------------------------------------------------

    def read_agencies(self) -> None:
        """Read agencies.txt."""
        df = self._read_df("agencies.txt", required=False)
        if df.empty:
            df = self._read_df("agency.txt", required=False)
            if df.empty:
                logger.warning("agencies.txt not found, skipping")
                return
        for _, row in df.iterrows():
            self.agencies.append(Agency(
                agency_id=row.get("agency_id", ""),
                agency_name=row["agency_name"],
                agency_timezone=row["agency_timezone"],
            ))

    def read_calendar(self) -> None:
        """Read calendar.txt with vectorized bool parsing."""
        df = self._read_df("calendar.txt", required=False)
        if df.empty:
            logger.info("calendar.txt not found, skipping")
            return

        bool_cols = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        for col in bool_cols:
            df[col] = df[col].eq("1")

        for _, row in df.iterrows():
            self.calendar.append(Calendar(
                service_id=row["service_id"],
                monday=bool(row["monday"]),
                tuesday=bool(row["tuesday"]),
                wednesday=bool(row["wednesday"]),
                thursday=bool(row["thursday"]),
                friday=bool(row["friday"]),
                saturday=bool(row["saturday"]),
                sunday=bool(row["sunday"]),
                start_date=row["start_date"],
                end_date=row["end_date"],
            ))

    def read_calendar_dates(self) -> None:
        """Read calendar_dates.txt."""
        df = self._read_df("calendar_dates.txt", required=False)
        if df.empty:
            logger.info("calendar_dates.txt not found, skipping")
            return

        df["_exception_type"] = pd.to_numeric(
            df["exception_type"].str.strip(), errors="coerce"
        )
        invalid = df["_exception_type"].isna() | df["exception_type"].str.strip().eq("")
        if invalid.any():
            logger.warning(
                f"{invalid.sum()} calendar_date rows with invalid exception_type, skipping"
            )
            df = df[~invalid]

        df["_exception_type"] = df["_exception_type"].astype(int)
        for _, row in df.iterrows():
            self.calendar_dates.append(CalendarDate(
                service_id=row["service_id"],
                date=row["date"],
                exception_type=int(row["_exception_type"]),
            ))

    def read_stops(self) -> None:
        """Read stops.txt with vectorized coordinate parsing."""
        df = self._read_df("stops.txt")
        if df.empty:
            return

        df["_lat"] = pd.to_numeric(df["stop_lat"].str.strip(), errors="coerce")
        df["_lon"] = pd.to_numeric(df["stop_lon"].str.strip(), errors="coerce")
        invalid = df["_lat"].isna() | df["_lon"].isna()
        if invalid.any():
            logger.warning(f"{invalid.sum()} stops with invalid coordinates, skipping")
            df = df[~invalid]

        df = df.sort_values("stop_id").reset_index(drop=True)

        for idx, row in df.iterrows():
            i = int(idx)  # type: ignore[arg-type]
            self.stop_id_map[row["stop_id"]] = i
            self.internal_to_stop[i] = row["stop_id"]
            self.stops.append(Stop(
                stop_id=row["stop_id"],
                name=row.get("stop_name", ""),
                lat=float(row["_lat"]),
                lon=float(row["_lon"]),
            ))

    def read_routes(self) -> None:
        """Read routes.txt with vectorized type parsing."""
        df = self._read_df("routes.txt")
        if df.empty:
            return

        df["_route_type"] = pd.to_numeric(
            df["route_type"].str.strip(), errors="coerce"
        ).fillna(3).astype(int)

        if "route_type" in df.columns:
            bad_type = df["route_type"].str.strip().eq("") | pd.to_numeric(
                df["route_type"].str.strip(), errors="coerce"
            ).isna()
            if bad_type.any():
                logger.warning(
                    f"{bad_type.sum()} routes with invalid route_type, defaulting to 3 (bus)"
                )

        df = df.sort_values("route_id").reset_index(drop=True)

        for idx, row in df.iterrows():
            i = int(idx)  # type: ignore[arg-type]
            self.route_id_map[row["route_id"]] = i
            self.internal_to_route[i] = row["route_id"]
            self.routes.append(Route(
                route_id=row["route_id"],
                route_short_name=row.get("route_short_name", ""),
                route_long_name=row.get("route_long_name", ""),
                route_type=int(row["_route_type"]),
            ))

    def read_trips(self) -> None:
        """Read trips.txt and expose trips_df for fast route lookups."""
        df = self._read_df("trips.txt")
        if df.empty:
            return

        if "direction_id" not in df.columns:
            df["direction_id"] = "0"
        df["direction_id"] = (
            pd.to_numeric(
                df["direction_id"].replace("", "0"), errors="coerce"
            ).fillna(0).astype(int)
        )

        df = df.sort_values("trip_id").reset_index(drop=True)
        df["trip_id_internal"] = df.index

        # Build mappings
        self.trip_id_map = dict(zip(df["trip_id"], df["trip_id_internal"].astype(int)))
        self.internal_to_trip = dict(zip(df["trip_id_internal"].astype(int), df["trip_id"]))

        # Build Pydantic models
        for _, row in df.iterrows():
            self.trips.append(Trip(
                trip_id=row["trip_id"],
                route_id=row["route_id"],
                service_id=row["service_id"],
                direction_id=int(row["direction_id"]),
            ))

        # Expose DataFrame for TripBuilder / RouteBuilder
        self.trips_df = df[
            ["trip_id", "route_id", "service_id", "direction_id", "trip_id_internal"]
        ].copy()

    def read_stop_times(self) -> None:
        """Read stop_times.txt with vectorized parsing — produces stop_times_df."""
        df = self._read_df("stop_times.txt")
        if df.empty:
            return

        # Vectorized time parsing
        df["arrival_time"] = GTFSReader._parse_time_series(df["arrival_time"])
        dep_col = df["departure_time"] if "departure_time" in df.columns else df["arrival_time"]
        df["departure_time"] = GTFSReader._parse_time_series(dep_col)
        df["departure_time"] = df["departure_time"].fillna(df["arrival_time"])

        # Vectorized stop_sequence parsing
        df["stop_sequence"] = pd.to_numeric(df["stop_sequence"], errors="coerce")

        # Drop invalid rows
        invalid = df["arrival_time"].isna() | df["stop_sequence"].isna()
        if invalid.any():
            logger.warning(f"Dropping {invalid.sum()} stop_times with invalid time/sequence")
            df = df[~invalid]

        df["arrival_time"] = df["arrival_time"].astype(int)
        df["departure_time"] = df["departure_time"].astype(int)
        df["stop_sequence"] = df["stop_sequence"].astype(int)

        # Vectorized internal ID mapping
        df["stop_id_internal"] = df["stop_id"].map(self.stop_id_map)
        df["trip_id_internal"] = df["trip_id"].map(self.trip_id_map)

        unmapped = df["stop_id_internal"].isna() | df["trip_id_internal"].isna()
        if unmapped.any():
            logger.warning(f"Dropping {unmapped.sum()} stop_times with unknown stop/trip IDs")
            df = df[~unmapped]

        df["stop_id_internal"] = df["stop_id_internal"].astype(int)
        df["trip_id_internal"] = df["trip_id_internal"].astype(int)

        # Sort for deterministic ordering
        df = df.sort_values(["trip_id", "stop_sequence"]).reset_index(drop=True)

        self.stop_times_df = df[[
            "trip_id", "stop_id",
            "arrival_time", "departure_time", "stop_sequence",
            "trip_id_internal", "stop_id_internal",
        ]]

        # self.stop_times is intentionally kept empty — use stop_times_df instead
        logger.info(f"Loaded {len(self.stop_times_df)} stop_times")

    def read_transfers(self) -> None:
        """Read transfers.txt if present."""
        df = self._read_df("transfers.txt", required=False)
        if df.empty:
            logger.info("transfers.txt not found, no explicit transfers")
            return

        df["_min_time"] = pd.to_numeric(
            df.get("min_transfer_time", pd.Series(["0"] * len(df))).replace("", "0"),
            errors="coerce",
        ).fillna(0).astype(int)

        for _, row in df.iterrows():
            self.transfers.append(Transfer(
                from_stop_id=row["from_stop_id"],
                to_stop_id=row["to_stop_id"],
                min_transfer_time=int(row["_min_time"]),
            ))

    # ------------------------------------------------------------------
    # Lookup helpers (unchanged public API)
    # ------------------------------------------------------------------

    def get_internal_stop_id(self, gtfs_stop_id: str) -> int:
        """Get internal stop ID from GTFS stop ID."""
        return self.stop_id_map[gtfs_stop_id]

    def get_internal_route_id(self, gtfs_route_id: str) -> int:
        """Get internal route ID from GTFS route ID."""
        return self.route_id_map[gtfs_route_id]

    def get_internal_trip_id(self, gtfs_trip_id: str) -> int:
        """Get internal trip ID from GTFS trip ID."""
        return self.trip_id_map[gtfs_trip_id]
