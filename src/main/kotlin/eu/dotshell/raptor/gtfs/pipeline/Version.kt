package eu.dotshell.raptor.gtfs.pipeline

object Version {
    // Container/format version for routes, index and lines binaries (magic RRT2 / RLN2).
    const val SCHEMA_VERSION = 2
    // Stops binary carries its own version: RST3 adds the per-stop fare zone. Kept separate
    // so routes/index/lines stay byte-identical while stops evolve independently.
    const val STOPS_SCHEMA_VERSION = 3
    const val VERSION = "0.3.0"
}
