package eu.dotshell.raptor.gtfs.pipeline

object Version {
    // Container/format version for routes, index and lines binaries (magic RRT2 / RLN2).
    const val SCHEMA_VERSION = 2
    // Stops binary carries its own version: RST3 adds the per-stop fare zone. Kept separate
    // so routes/index/lines stay byte-identical while stops evolve independently.
    const val STOPS_SCHEMA_VERSION = 3
    // The artifact that produced a dataset, generated from gradle.properties. Unlike the two
    // above it says nothing about what a consumer can parse — it is provenance, not a contract.
    const val VERSION = PIPELINE_VERSION
}
