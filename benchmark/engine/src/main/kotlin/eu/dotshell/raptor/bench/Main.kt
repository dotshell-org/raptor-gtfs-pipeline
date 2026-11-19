package eu.dotshell.raptor.bench

import io.raptor.Location
import io.raptor.PeriodData
import io.raptor.RaptorLibrary
import io.raptor.WalkingParams
import io.raptor.core.JourneyLeg
import io.raptor.model.Stop
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
 *         [--mode full|heap|points|school] [--queries 1000] [--warmup 200] [--loads 5] [--seed 12345]
 *         [--areas areas.csv] [--scenarios scenarios.csv] [--max-rounds 5]
 *
 * full: cold and warm load times, retained heap, latency of random, local and named
 * queries, forward and arrive-by. heap: load and a short run of queries only, to learn
 * whether the tier fits under the -Xmx it was started with. points: what searching from an
 * address costs, against searching from stops, on the same trips (see [pointSets]). school:
 * the same trips with and without the school lines (see [schoolSets]). An
 * OutOfMemoryError is caught and reported with the phase it struck in, so the driver can tell
 * "does not fit" from "broken".
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
    /** Where to write the class histogram of the loaded network (what the heap holds, by class). */
    val histogram = values["histogram"]?.let(::File)
    /**
     * bytes: read both files, then build (both arrays alive during the build, as before).
     * files: give raptor-kmp providers that read each file when it needs it, as an app does:
     * at most one file's bytes alive at a time, none kept.
     */
    val load = values["load"] ?: "bytes"
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
    collect()
    resetPeaks()
    val baseline = usedHeapMb()
    if (options.mode == "periods") return periodsRun(options, baseline)
    require(stopsFile.exists() && routesFile.exists()) { "no stops.bin / routes.bin in ${options.data}" }

    phase = "read"
    var started = System.nanoTime()
    var stopsBytes: ByteArray? = if (options.load == "files") null else stopsFile.readBytes()
    var routesBytes: ByteArray? = if (options.load == "files") null else routesFile.readBytes()
    val coldRead = msSince(started)

    phase = "build"
    started = System.nanoTime()
    var library = if (options.load == "files") fileLibrary(options.data)
                  else RaptorLibrary(stopsBytes!!, routesBytes!!)
    val period = library.getCurrentPeriod()
    library.getStops(period)  // the network is built lazily: force it, as raptor-kmp's LoadBenchmark does
    val coldBuild = msSince(started)
    stopsBytes = null
    routesBytes = null

    phase = "measure heap"
    collect()
    val retained = usedHeapMb() - baseline
    options.histogram?.let { file ->
        // The JVM's own GC.class_histogram (as jcmd prints it), right after the network is built.
        val text = ManagementFactory.getPlatformMBeanServer().invoke(
            javax.management.ObjectName("com.sun.management:type=DiagnosticCommand"), "gcClassHistogram",
            arrayOf<Any>(arrayOf<String>()), arrayOf("[Ljava.lang.String;")) as String
        file.parentFile?.mkdirs()
        file.writeText(text.lines().take(45).joinToString("\n"))
    }

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
    val extras = mutableMapOf<String, Double>()
    if (options.mode == "points") {
        phase = "points"
        querySets += pointSets(library, stops, index, options, extras)
    } else if (options.mode == "school") {
        phase = "school"
        querySets += schoolSets(library, ids, index, options, extras)
    } else if (options.mode == "golden") {
        phase = "golden"
        val (sets, perQuery) = goldenSets(library, stops, ids, index, options)
        return base(options).copy(files = Files(stopsFile.length(), routesFile.length()), network = network,
                                  heap = Heap(retainedMb = retained, peakMb = peakHeapMb()), golden = sets, goldenQueries = perQuery)
    } else if (options.mode == "full") {
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
        extras = extras,
    )
}

/** A library whose files are read when raptor-kmp builds the network, not before. */
private fun fileLibrary(dir: File, name: String = "bench") = RaptorLibrary(listOf(
    PeriodData(name, { File(dir, "stops.bin").readBytes() }, { File(dir, "routes.bin").readBytes() })))

/**
 * A live network's day types one after the other in one JVM, as an app switching dates: each
 * is built from its files once the previous one is let go, then answers random queries forward
 * and arrive-by and address queries. Run under a small -Xmx, it tells whether every day type
 * fits, and the peak heap of the whole run.
 */
private fun periodsRun(options: Options, baseline: Double): Report {
    val dirs = options.data.listFiles { f -> f.isDirectory && File(f, "routes.bin").exists() }.orEmpty()
        .sortedBy { listOf("semaine", "samedi", "dimanche", "vacances").indexOf(it.name).let { i -> if (i < 0) 99 else i } }
    require(dirs.isNotEmpty()) { "no day type folders in ${options.data}" }
    val querySets = mutableListOf<QuerySet>()
    val extras = linkedMapOf<String, Double>()
    var library: RaptorLibrary? = null
    for (dir in dirs) {
        phase = "build ${dir.name}"
        library = null
        collect()
        val started = System.nanoTime()
        val lib = fileLibrary(dir, dir.name)
        library = lib
        val stops = lib.getStops(dir.name)
        extras["${dir.name}.buildMs"] = msSince(started)
        collect()
        extras["${dir.name}.retainedMb"] = usedHeapMb() - baseline
        phase = "queries ${dir.name}"
        val ids = stops.map { it.id }
        val random = randomQueries(ids, options.queries, options.seed)
        randomQueries(ids, 100, options.seed + 1).forEach { forward(lib, it, options.maxRounds) }
        querySets += timeSet("${dir.name}:random", "forward", random) { forward(lib, it, options.maxRounds) }
        querySets += timeSet("${dir.name}:random", "arrive_by", random.take(300).map { it.copy(time = it.time + 3600) }) {
            arriveBy(lib, it, options.maxRounds)
        }
        querySets += timeAll("${dir.name}:address", "forward", randomPoints(stops, 300, options.seed), { it.time }) { p ->
            lib.getOptimizedPaths(Location.Point(p.oLat, p.oLon), Location.Point(p.dLat, p.dLon), p.time, maxRounds = options.maxRounds)
        }
    }
    phase = "done"
    return base(options).copy(heap = Heap(retainedMb = extras.filterKeys { it.endsWith("retainedMb") }.values.maxOrNull() ?: 0.0,
                                          peakMb = peakHeapMb()),
                              querySets = querySets, extras = extras)
}

/** Every field of every journey, in order: two engines that agree here return the same thing. */
private fun canonical(journeys: List<List<JourneyLeg>>): String = journeys.joinToString(";") { legs ->
    legs.joinToString("/") { l ->
        listOf(l.legType, l.fromStopIndex, l.toStopIndex, l.departureTime, l.arrivalTime, l.routeName, l.direction,
               l.isTransfer, l.intermediateStopIndices.joinToString(","), l.intermediateArrivalTimes.joinToString(","),
               l.fromLat, l.fromLon, l.toLat, l.toLon).joinToString("|")
    }
}

private fun sha(text: String): String =
    java.security.MessageDigest.getInstance("SHA-256").digest(text.toByteArray()).joinToString("") { "%02x".format(it) }.take(16)

/**
 * Golden journeys: the exact output of fixed queries, hashed, so two engine builds can be
 * compared (an optimization must return the very same journeys). Sets: random stop pairs
 * forward and arrive-by, the local sets of areas.csv, addresses forward and arrive-by, and the
 * school lines left out when the network has its list.
 */
private fun goldenSets(library: RaptorLibrary, stops: List<Stop>, ids: List<Int>, index: StopIndex, options: Options):
        Pair<Map<String, String>, Map<String, List<String>>> {
    val rounds = options.maxRounds
    val sets = linkedMapOf<String, List<() -> List<List<JourneyLeg>>>>()
    val random = randomQueries(ids, options.queries, options.seed)
    sets["random:forward"] = random.map { q -> { forward(library, q, rounds) } }
    sets["random:arrive_by"] = random.take(300).map { q -> { arriveBy(library, q.copy(time = q.time + 3600), rounds) } }
    options.areas?.let(::readAreas)?.forEach { area ->
        localQueries(area, index, options.seed)?.let { local ->
            sets["${area.name}:forward"] = local.map { q -> { forward(library, q, rounds) } }
            sets["${area.name}:arrive_by"] = local.take(100).map { q -> { arriveBy(library, q.copy(time = q.time + 3600), rounds) } }
        }
    }
    val points = randomPoints(stops, 300, options.seed)
    fun at(p: PointQuery) = Pair(Location.Point(p.oLat, p.oLon), Location.Point(p.dLat, p.dLon))
    sets["address:forward"] = points.map { p -> { at(p).let { (o, d) -> library.getOptimizedPaths(o, d, p.time, maxRounds = rounds) } } }
    sets["address:arrive_by"] = points.take(100).map { p ->
        { at(p).let { (o, d) -> library.getOptimizedPathsArriveBy(o, d, p.time + 3600, maxRounds = rounds) } }
    }
    val school = schoolRoutes(options.data)
    if (school.isNotEmpty()) {
        sets["no-school:forward"] = random.take(200).map { q ->
            { library.getOptimizedPaths(q.origins, q.destinations, q.time, maxRounds = rounds, blockedRouteIds = school) }
        }
    }
    val perQuery = sets.mapValues { (_, calls) -> calls.map { sha(canonical(it())) } }
    return Pair(perQuery.mapValues { (_, hashes) -> sha(hashes.joinToString("")) }, perQuery)
}

/**
 * The "school lines" switch: the same trips with every line, then with the school lines left
 * out (school_routes.json, raptor-kmp's blockedRouteIds). Random and local sets, forward and
 * arrive-by. The found counts tell how many trips need a school line; the latencies, what the
 * filter costs (raptor-kmp checks every route against the set once per search).
 */
private fun schoolSets(library: RaptorLibrary, ids: List<Int>, index: StopIndex, options: Options,
                       extras: MutableMap<String, Double>): List<QuerySet> {
    val blocked = schoolRoutes(options.data)
    require(blocked.isNotEmpty()) { "no school_routes.json in ${options.data}" }
    extras["schoolRouteIds"] = blocked.size.toDouble()
    val period = library.getCurrentPeriod()
    extras["schoolTrips"] = library.getRoutes(period).filter { it.id in blocked }.sumOf { it.tripCount }.toDouble()
    val rounds = options.maxRounds
    fun run(q: Query, backward: Boolean, without: Set<Int>) =
        if (backward) library.getOptimizedPathsArriveBy(q.origins, q.destinations, q.time, maxRounds = rounds, blockedRouteIds = without)
        else library.getOptimizedPaths(q.origins, q.destinations, q.time, maxRounds = rounds, blockedRouteIds = without)

    val sets = mutableListOf("random" to randomQueries(ids, options.queries, options.seed))
    options.areas?.let(::readAreas)?.forEach { area -> localQueries(area, index, options.seed)?.let { sets += area.name to it } }
    val results = mutableListOf<QuerySet>()
    for ((name, queries) in sets) {
        for (backward in listOf(false, true)) {
            val direction = if (backward) "arrive_by" else "forward"
            val timed = if (backward) queries.map { it.copy(time = it.time + 3600) } else queries
            results += timeSet("$name:all", direction, timed) { run(it, backward, emptySet()) }
            results += timeSet("$name:no-school", direction, timed) { run(it, backward, blocked) }
        }
    }
    return results
}

/**
 * Searching from an address against searching from stops, on the same trips. Each trip, two
 * points, is timed three ways (the stops are looked up before the clock starts):
 *
 *  - nearest: the stop closest to each point, as when a rider picks a stop;
 *  - stops:   every stop within 500 m of each point, no walk counted, a multi-stop place;
 *  - address: Location.Point, those same stops each with its own walk, plus the walk-only
 *             journey under 1 km: what Pelo sends for an address.
 *
 * Forward for the three, arrive-by for nearest and address. Trips: the random set's stops each
 * moved up to 300 m (an address near a stop), and the very points the local sets draw in
 * areas.csv. extras.addressGridMb is the heap the first address search adds: raptor-kmp's
 * spatial grid of the stops, built once.
 */
private fun pointSets(library: RaptorLibrary, stops: List<Stop>, index: StopIndex, options: Options,
                      extras: MutableMap<String, Double>): List<QuerySet> {
    val radius = WalkingParams.DEFAULT.maxAccessEgressDistanceMeters
    val rounds = options.maxRounds
    fun address(p: PointQuery, backward: Boolean = false): List<List<JourneyLeg>> {
        val o = Location.Point(p.oLat, p.oLon)
        val d = Location.Point(p.dLat, p.dLon)
        return if (backward) library.getOptimizedPathsArriveBy(o, d, p.time, maxRounds = rounds)
               else library.getOptimizedPaths(o, d, p.time, maxRounds = rounds)
    }

    collect()
    val before = usedHeapMb()
    address(PointQuery(stops[0].lat, stops[0].lon, stops[1].lat, stops[1].lon, 8 * 3600))
    collect()
    extras["addressGridMb"] = usedHeapMb() - before
    randomPoints(stops, 50, options.seed + 2).forEach { address(it) }  // JIT: the address path

    val sets = mutableListOf("random" to randomPoints(stops, options.queries, options.seed))
    options.areas?.let(::readAreas)?.forEach { area -> localPoints(area, index, options.seed)?.let { sets += area.name to it } }
    val results = mutableListOf<QuerySet>()
    for ((name, points) in sets) {
        val nearest = points.map { p ->
            Query(listOfNotNull(index.nearest(p.oLat, p.oLon)?.id), listOfNotNull(index.nearest(p.dLat, p.dLon)?.id), p.time)
        }
        val around = points.map { p ->
            Query(index.within(p.oLat, p.oLon, radius).map { it.id }, index.within(p.dLat, p.dLon, radius).map { it.id }, p.time)
        }
        fun stopsOrNothing(q: Query, backward: Boolean = false) = when {
            q.origins.isEmpty() || q.destinations.isEmpty() -> emptyList()
            backward -> arriveBy(library, q, rounds)
            else -> forward(library, q, rounds)
        }
        results += timeSet("$name:nearest", "forward", nearest) { stopsOrNothing(it) }
        results += timeSet("$name:stops", "forward", around) { stopsOrNothing(it) }
        results += timeAll("$name:address", "forward", points, { it.time }) { address(it) }
        results += timeSet("$name:nearest", "arrive_by", nearest.map { it.copy(time = it.time + 3600) }) { stopsOrNothing(it, true) }
        results += timeAll("$name:address", "arrive_by", points.map { it.copy(time = it.time + 3600) }, { it.time }) { address(it, true) }
    }
    return results
}

private fun forward(library: RaptorLibrary, q: Query, maxRounds: Int) =
    library.getOptimizedPaths(q.origins, q.destinations, q.time, maxRounds = maxRounds)

private fun arriveBy(library: RaptorLibrary, q: Query, maxRounds: Int) =
    library.getOptimizedPathsArriveBy(q.origins, q.destinations, q.time, maxRounds = maxRounds)

/** The journey a rider would take: the one arriving first. */
private fun best(journeys: List<List<JourneyLeg>>): List<JourneyLeg>? =
    journeys.filter { it.isNotEmpty() }.minByOrNull { it.last().arrivalTime }

private fun timeSet(name: String, direction: String, queries: List<Query>, call: (Query) -> List<List<JourneyLeg>>): QuerySet =
    timeAll(name, direction, queries, { it.time }, call)

private fun <T> timeAll(name: String, direction: String, queries: List<T>, timeOf: (T) -> Int,
                        call: (T) -> List<List<JourneyLeg>>): QuerySet {
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
        val start = if (direction == "forward") timeOf(q) else journey.first().departureTime
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
