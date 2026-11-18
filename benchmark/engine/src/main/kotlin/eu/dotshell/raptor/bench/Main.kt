package eu.dotshell.raptor.bench

import io.raptor.RaptorLibrary
import io.raptor.core.JourneyLeg
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.io.File
import java.lang.management.ManagementFactory
import java.lang.management.MemoryType
import kotlin.system.exitProcess

/**
 * Loads one tier's stops.bin / routes.bin into raptor-kmp and measures it.
 *
 *     benchmark-engine --data data/raptor/france/bench --tier france --out france.json
 *         [--mode full|heap] [--queries 1000] [--warmup 200] [--loads 5] [--seed 12345]
 *         [--areas areas.csv] [--scenarios scenarios.csv] [--max-rounds 5]
 *
 * full: cold and warm load times, retained heap, latency of random, local and named
 * queries, forward and arrive-by. heap: load and a short run of queries only, to learn
 * whether the tier fits under the -Xmx it was started with. An OutOfMemoryError is caught and
 * reported with the phase it struck in, so the driver can tell "does not fit" from "broken".
 */

private var phase = "start"
private val json = Json { prettyPrint = true; encodeDefaults = true }

private class Options(args: Array<String>) {
    private val values = args.toList().chunked(2).associate { (k, v) -> k.removePrefix("--") to v }
    val data = File(values["data"] ?: error("--data is required"))
    val tier = values["tier"] ?: data.parentFile?.name ?: "?"
    val out = File(values["out"] ?: "engine.json")
    val mode = values["mode"] ?: "full"
    val queries = values["queries"]?.toInt() ?: 1000
    val warmup = values["warmup"]?.toInt() ?: 200
    val loads = values["loads"]?.toInt() ?: 5
    val seed = values["seed"]?.toLong() ?: 12345L
    val areas = values["areas"]?.let(::File)
    val scenarios = values["scenarios"]?.let(::File)
    val maxRounds = values["max-rounds"]?.toInt() ?: 5
}

fun main(args: Array<String>) {
    val options = Options(args)
    val report = try {
        run(options)
    } catch (error: OutOfMemoryError) {
        // Everything run() allocated is unreachable once it has unwound: there is room to report.
        base(options).copy(status = "out_of_memory", failedDuring = phase, error = error.toString())
    } catch (error: Exception) {
        base(options).copy(status = "failed", failedDuring = phase, error = error.toString())
    }
    options.out.parentFile?.mkdirs()
    options.out.writeText(json.encodeToString(report))
    println("${report.tier}: ${report.status}" + (report.failedDuring?.let { " during $it" } ?: ""))
    exitProcess(if (report.status == "ok") 0 else 2)
}

private fun engineVersion(): String =
    object {}.javaClass.getResource("/raptor-kmp.version")?.readText()?.trim() ?: "?"

private fun base(options: Options) = Report(
    tier = options.tier, status = "ok", engineVersion = engineVersion(),
    java = System.getProperty("java.runtime.version") ?: "?",
    maxHeapMb = Runtime.getRuntime().maxMemory() / (1024 * 1024),
)

private fun usedHeapMb(): Double = ManagementFactory.getMemoryMXBean().heapMemoryUsage.used / 1024.0 / 1024.0

private fun peakHeapMb(): Double = ManagementFactory.getMemoryPoolMXBeans()
    .filter { it.type == MemoryType.HEAP }.sumOf { it.peakUsage.used } / 1024.0 / 1024.0

private fun resetPeaks() = ManagementFactory.getMemoryPoolMXBeans().forEach { it.resetPeakUsage() }

private fun collect() = repeat(3) { System.gc(); Thread.sleep(150) }

private fun msSince(start: Long) = (System.nanoTime() - start) / 1e6

private fun run(options: Options): Report {
    val stopsFile = File(options.data, "stops.bin")
    val routesFile = File(options.data, "routes.bin")
    require(stopsFile.exists() && routesFile.exists()) { "no stops.bin / routes.bin in ${options.data}" }

    collect()
    resetPeaks()
    val baseline = usedHeapMb()

    phase = "read"
    var started = System.nanoTime()
    var stopsBytes: ByteArray? = stopsFile.readBytes()
    var routesBytes: ByteArray? = routesFile.readBytes()
    val coldRead = msSince(started)

    phase = "build"
    started = System.nanoTime()
    var library = RaptorLibrary(stopsBytes!!, routesBytes!!)
    val period = library.getCurrentPeriod()
    library.getStops(period)  // the network is built lazily: force it, as raptor-kmp's LoadBenchmark does
    val coldBuild = msSince(started)
    stopsBytes = null
    routesBytes = null

    phase = "measure heap"
    collect()
    val retained = usedHeapMb() - baseline

    val stops = library.getStops(period)
    val routes = library.getRoutes(period)
    val byName = stops.groupingBy { it.name }.eachCount()
    val network = NetworkSize(
        stops = stops.size, routes = routes.size,
        trips = routes.sumOf { it.tripCount.toLong() },
        stopTimes = routes.sumOf { it.tripCount.toLong() * it.stopCountInRoute },
        transfers = stops.sumOf { it.transfers.size.toLong() },
        implicitTransferPairs = byName.values.sumOf { it.toLong() * (it - 1) },
        largestNameGroup = byName.values.maxOrNull() ?: 0,
    )

    val warm = mutableListOf<Double>()
    if (options.mode == "full") {
        phase = "warm loads"
        repeat(options.loads) {
            val s = stopsFile.readBytes()
            val r = routesFile.readBytes()
            val t = System.nanoTime()
            val again = RaptorLibrary(s, r)
            again.getStops(again.getCurrentPeriod())
            warm += msSince(t)
            library = again  // the previous one becomes garbage: never two networks plus a third
            collect()
        }
    }

    phase = "queries"
    val ids = stops.map { it.id }
    val index = StopIndex(stops)
    val querySets = mutableListOf<QuerySet>()
    val scenarios = mutableListOf<Scenario>()

    randomQueries(ids, options.warmup, options.seed + 1).forEach { forward(library, it, options.maxRounds) }
    if (options.mode == "full") {
        val random = randomQueries(ids, options.queries, options.seed)
        querySets += timeSet("random", "forward", random) { forward(library, it, options.maxRounds) }
        querySets += timeSet("random", "arrive_by", random.map { it.copy(time = it.time + 3600) }) {
            arriveBy(library, it, options.maxRounds)
        }
        options.areas?.let(::readAreas)?.forEach { area ->
            val local = localQueries(area, index, options.seed)
            if (local == null) {
                querySets += QuerySet(area.name, "forward", 0, 0, Latency(0.0, 0.0, 0.0, 0.0, 0.0, 0.0), note = "area not covered by this tier")
            } else {
                querySets += timeSet(area.name, "forward", local) { forward(library, it, options.maxRounds) }
                querySets += timeSet(area.name, "arrive_by", local.map { it.copy(time = it.time + 3600) }) {
                    arriveBy(library, it, options.maxRounds)
                }
            }
        }
        options.scenarios?.let(::readScenarios)?.forEach { trip -> scenarios += scenario(library, index, trip, options.maxRounds) }
    } else {
        val random = randomQueries(ids, minOf(options.queries, 200), options.seed)
        querySets += timeSet("random", "forward", random) { forward(library, it, options.maxRounds) }
    }

    phase = "done"
    return base(options).copy(
        files = Files(stopsFile.length(), routesFile.length()),
        network = network,
        load = Load(coldRead, coldBuild, warm, warm.sorted().let { if (it.isEmpty()) null else it[it.size / 2] }),
        heap = Heap(retainedMb = retained, peakMb = peakHeapMb()),
        querySets = querySets,
        scenarios = scenarios,
    )
}

private fun forward(library: RaptorLibrary, q: Query, maxRounds: Int) =
    library.getOptimizedPaths(q.origins, q.destinations, q.time, maxRounds = maxRounds)

private fun arriveBy(library: RaptorLibrary, q: Query, maxRounds: Int) =
    library.getOptimizedPathsArriveBy(q.origins, q.destinations, q.time, maxRounds = maxRounds)

/** The journey a rider would take: the one arriving first. */
private fun best(journeys: List<List<JourneyLeg>>): List<JourneyLeg>? =
    journeys.filter { it.isNotEmpty() }.minByOrNull { it.last().arrivalTime }

private fun timeSet(name: String, direction: String, queries: List<Query>, call: (Query) -> List<List<JourneyLeg>>): QuerySet {
    val times = DoubleArray(queries.size)
    val durations = mutableListOf<Double>()
    val legs = mutableListOf<Double>()
    var found = 0
    queries.forEachIndexed { i, q ->
        val t = System.nanoTime()
        val journeys = call(q)
        times[i] = msSince(t)
        val journey = best(journeys) ?: return@forEachIndexed
        found++
        val start = if (direction == "forward") q.time else journey.first().departureTime
        durations += (journey.last().arrivalTime - start) / 60.0
        legs += journey.count { !it.isTransfer }.toDouble()
    }
    times.sort()
    fun pct(p: Double) = if (times.isEmpty()) 0.0 else times[((p * times.size).toInt()).coerceAtMost(times.size - 1)]
    return QuerySet(
        name = name, direction = direction, queries = queries.size, found = found,
        latencyMs = Latency(times.average().takeIf { !it.isNaN() } ?: 0.0, pct(0.50), pct(0.90), pct(0.95), pct(0.99), times.lastOrNull() ?: 0.0),
        medianDurationMin = durations.sorted().let { if (it.isEmpty()) null else it[it.size / 2] },
        medianTransitLegs = legs.sorted().let { if (it.isEmpty()) null else it[it.size / 2] },
    )
}

private fun scenario(library: RaptorLibrary, index: StopIndex, trip: NamedTrip, maxRounds: Int): Scenario {
    val origins = index.within(trip.oLat, trip.oLon, trip.radius).map { it.id }
    val destinations = index.within(trip.dLat, trip.dLon, trip.radius).map { it.id }
    val base = Scenario(trip.name, trip.kind, origins.size, destinations.size, hhmm(trip.departure), found = false)
    if (origins.isEmpty() || destinations.isEmpty()) return base.copy(note = "not covered by this tier")
    val query = Query(origins, destinations, trip.departure)
    val runs = (1..5).map {
        val t = System.nanoTime()
        val journeys = forward(library, query, maxRounds)
        Pair(msSince(t), journeys)
    }
    val latency = runs.map { it.first }.sorted()[2]
    val journey = best(runs.last().second) ?: return base.copy(latencyMs = latency, note = "no journey within $maxRounds rounds")
    val transit = journey.filter { !it.isTransfer }
    return base.copy(
        found = true, latencyMs = latency, arrival = hhmm(journey.last().arrivalTime),
        durationMin = (journey.last().arrivalTime - trip.departure) / 60, transitLegs = transit.size,
        routes = transit.map { it.routeName ?: "?" },
    )
}
