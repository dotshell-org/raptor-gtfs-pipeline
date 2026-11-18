"""The routing engine, kept running in a JVM: raptor-kmp behind a line-based JSON pipe.

The server is the `ServeKt` entry point of the :benchmark-engine module. It loads one
network once; every request then costs a single raptor-kmp call, timed inside the JVM.
"""

from __future__ import annotations

import json
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

from ..convert import java_executable
from ..engine import ENGINE_INSTALL

SERVER_CLASS = "eu.dotshell.raptor.bench.ServeKt"


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
                [(p[0], p[1]) for p in l.get("path", [])])
            for l in legs]))
    return RouteResult(answer["ms"], journeys, answer.get("maxRounds"))


class EngineServer:
    """One JVM with one network loaded. Thread-safe: requests are serialized."""

    def __init__(self, data_dir: Path, java: str | None = None, xmx: str = "2g"):
        if not (ENGINE_INSTALL / "lib").exists():
            raise EngineError(f"{ENGINE_INSTALL} is missing: run ./gradlew :benchmark-engine:installDist")
        if not (data_dir / "routes.bin").exists():
            raise EngineError(f"no routes.bin in {data_dir}: convert that tier first")
        self._lock = threading.Lock()
        self._process = subprocess.Popen(
            [java_executable(java), f"-Xmx{xmx}", "-cp", str(ENGINE_INSTALL / "lib" / "*"), SERVER_CLASS, "--data", str(data_dir)],
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

    def route(self, origins: list[int], destinations: list[int], time: int, arrive_by: bool = False,
              max_rounds: int = 5) -> RouteResult:
        """max_rounds is RAPTOR's round limit: the most rides a journey may take (changes + 1)."""
        return parse_route(self.request({"op": "route", "from": origins, "to": destinations, "time": time,
                                         "arriveBy": arrive_by, "maxRounds": max_rounds}))

    def close(self) -> None:
        try:
            with self._lock:
                self._process.stdin.write('{"op":"quit"}\n')
                self._process.stdin.flush()
            self._process.wait(timeout=5)
        except Exception:
            self._process.kill()
