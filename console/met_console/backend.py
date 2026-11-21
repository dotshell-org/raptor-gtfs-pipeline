"""The routing engine, kept running in a JVM: raptor-kmp behind a line-based JSON pipe.

The server is console/engine's ServeKt. It loads one day type of the installed version once;
every request then costs a single raptor-kmp call, timed inside the JVM.
"""

from __future__ import annotations

import json
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .paths import engine_classpath, engine_missing, java_executable

SERVER_CLASS = "eu.dotshell.met.console.ServeKt"


class EngineError(RuntimeError):
    pass


@dataclass
class Leg:
    from_name: str
    to_name: str
    departure: int
    arrival: int
    route: str | None
    direction: str | None
    walk: bool
    stops: int
    path: list[tuple[float, float]] = field(default_factory=list)
    # transit, transfer, or a walk to/from an address: walk_access, walk_egress, walk_direct
    kind: str = "transit"


@dataclass
class Journey:
    legs: list[Leg]

    @property
    def departure(self) -> int:
        return self.legs[0].departure

    @property
    def arrival(self) -> int:
        return self.legs[-1].arrival

    @property
    def rides(self) -> list[Leg]:
        return [leg for leg in self.legs if not leg.walk]

    @property
    def changes(self) -> int:
        return max(0, len(self.rides) - 1)


@dataclass
class RouteResult:
    ms: float
    journeys: list[Journey]
    max_rounds: int | None = None  # the limit the engine ran with: most rides, i.e. changes + 1
    # Addresses only: nothing within 500 m on foot, so the engine walked up to walk_radius metres
    fallback: bool = False
    walk_radius: float | None = None
    # School lines left out of this search (route numbers), 0 when they were all in
    school_blocked: int = 0

    def best(self, arrive_by: bool = False) -> Journey | None:
        if not self.journeys:
            return None
        if arrive_by:  # latest departure that still arrives in time
            return max(self.journeys, key=lambda j: (j.departure, -j.changes))
        return min(self.journeys, key=lambda j: (j.arrival, j.changes))


def parse_route(answer: dict) -> RouteResult:
    journeys = []
    for legs in answer.get("journeys", []):
        journeys.append(Journey([
            Leg(l["from"], l["to"], l["dep"], l["arr"], l.get("route"), l.get("direction"), l["walk"], l.get("stops", 0),
                [(p[0], p[1]) for p in l.get("path", [])], l.get("kind", "transfer" if l["walk"] else "transit"))
            for l in legs]))
    return RouteResult(answer["ms"], journeys, answer.get("maxRounds"), answer.get("fallback", False),
                       answer.get("walkRadius"), answer.get("schoolBlocked", 0))


class EngineServer:
    """One JVM with one day type loaded. Thread-safe: requests are serialized.

    `data_dir` is a version's folder, one sub-folder per day type: info["periods"] lists them
    and `period()` switches.
    """

    def __init__(self, data_dir: Path, java: str | None = None, xmx: str = "1g"):
        missing = engine_missing()
        if missing:
            raise EngineError(missing)
        if not (data_dir / "routes.bin").exists() and not list(data_dir.glob("*/routes.bin")):
            raise EngineError(f"pas de routes.bin dans {data_dir}")
        self._lock = threading.Lock()
        self._process = subprocess.Popen(
            [java_executable(java), f"-Xmx{xmx}", "-cp", engine_classpath(), SERVER_CLASS, "--data", str(data_dir)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
        self.info = self._read()
        if self.info.get("type") != "ready":
            raise EngineError(f"engine did not start: {self.info}")

    def _read(self) -> dict:
        line = self._process.stdout.readline()
        if not line:
            error = self._process.stderr.read() if self._process.stderr else ""
            raise EngineError(f"engine stopped: {error.strip()[-400:] or 'no output'}")
        return json.loads(line)

    def request(self, payload: dict) -> dict:
        with self._lock:
            self._process.stdin.write(json.dumps(payload) + "\n")
            self._process.stdin.flush()
            answer = self._read()
        if answer.get("type") == "error":
            raise EngineError(answer.get("message", "engine error"))
        return answer

    def stops(self) -> list[tuple[int, str, float, float]]:
        return [tuple(s) for s in self.request({"op": "stops"})["stops"]]

    def route(self, origins: list[int] | dict, destinations: list[int] | dict, time: int, arrive_by: bool = False,
              max_rounds: int = 5, fallback_walk_m: float | None = None, school: bool = True) -> RouteResult:
        """Each end is stop ids, or an address {"lat", "lon", "label"} (Address.endpoint()).

        max_rounds is RAPTOR's round limit: the most rides a journey may take (changes + 1).
        fallback_walk_m: when an address finds nothing within 500 m on foot, search again walking
        up to that far (Pelo uses 6 000 m). school=False leaves the school lines out (when the
        day has its school_routes.json: info["schoolRoutes"] > 0).
        """
        payload = {"op": "route", "from": origins, "to": destinations, "time": time,
                   "arriveBy": arrive_by, "maxRounds": max_rounds}
        if fallback_walk_m:
            payload["fallbackWalkMeters"] = fallback_walk_m
        if not school:
            payload["school"] = False
        return parse_route(self.request(payload))

    def period(self, name: str) -> dict:
        """Load another day type (one at a time): its new info."""
        self.info = self.request({"op": "period", "name": name})
        return self.info

    def routes(self) -> list[tuple[int, str]]:
        return [tuple(r) for r in self.request({"op": "routes"})["routes"]]

    def close(self) -> None:
        try:
            with self._lock:
                self._process.stdin.write('{"op":"quit"}\n')
                self._process.stdin.flush()
            self._process.wait(timeout=5)
        except Exception:
            self._process.kill()
