package eu.dotshell.raptor.bench

import kotlinx.serialization.Serializable

/** Everything one run measures, written as JSON for the Python driver. */
@Serializable
data class Report(
    val tier: String,
    val status: String,                 // ok | out_of_memory | failed
    val failedDuring: String? = null,
    val error: String? = null,
    val engineVersion: String,
    val java: String,
    val maxHeapMb: Long,
    val files: Files? = null,
    val network: NetworkSize? = null,
    val load: Load? = null,
    val heap: Heap? = null,
    val querySets: List<QuerySet> = emptyList(),
    val scenarios: List<Scenario> = emptyList(),
    /** Single figures a mode adds, e.g. points mode: the heap the address search adds. */
    val extras: Map<String, Double> = emptyMap(),
    /** golden mode: one hash per query set over every journey returned, and per query. */
    val golden: Map<String, String> = emptyMap(),
    val goldenQueries: Map<String, List<String>> = emptyMap(),
)

@Serializable
data class Files(val stopsBytes: Long, val routesBytes: Long)

@Serializable
data class NetworkSize(
    val stops: Int,
    val routes: Int,
    val trips: Long,
    val stopTimes: Long,
    val transfers: Long,
    /** Σ k·(k−1) over stop names: the same-name links raptor-kmp builds (implicitTransferData). */
    val implicitTransferPairs: Long,
    val largestNameGroup: Int,
)

@Serializable
data class Load(
    /** First load in a fresh JVM: reading the files, then deserialization + Network construction. */
    val coldReadMs: Double,
    val coldBuildMs: Double,
    /** Later loads in the same JVM (JIT warm), build only; empty in heap-sweep mode. */
    val warmBuildMs: List<Double>,
    val warmBuildMedianMs: Double?,
)

@Serializable
data class Heap(
    /** Heap held by the loaded library once garbage is collected, file bytes released. */
    val retainedMb: Double,
    /** Highest heap occupancy seen during the run, garbage included. */
    val peakMb: Double,
)

@Serializable
data class QuerySet(
    val name: String,
    val direction: String,              // forward | arrive_by
    val queries: Int,
    val found: Int,
    val latencyMs: Latency,
    /** Median over the found journeys, door to door, minutes; and transit legs. */
    val medianDurationMin: Double? = null,
    val medianTransitLegs: Double? = null,
    val note: String? = null,
)

@Serializable
data class Latency(
    val mean: Double, val p50: Double, val p90: Double, val p95: Double, val p99: Double, val max: Double,
)

@Serializable
data class Scenario(
    val name: String,
    val kind: String,
    val originStops: Int,
    val destinationStops: Int,
    val departure: String,
    val found: Boolean,
    val latencyMs: Double? = null,       // median of 5 runs
    val arrival: String? = null,
    val durationMin: Int? = null,
    val transitLegs: Int? = null,
    val routes: List<String> = emptyList(),
    val note: String? = null,
)
