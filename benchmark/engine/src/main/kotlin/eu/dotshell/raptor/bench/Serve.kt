package eu.dotshell.raptor.bench

import io.raptor.Location
import io.raptor.RaptorLibrary
import io.raptor.WalkingParams
import io.raptor.core.JourneyLeg
import io.raptor.core.LegType
import io.raptor.model.Stop
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.io.FileDescriptor
import java.io.FileOutputStream
import java.io.PrintStream
import java.lang.management.ManagementFactory

/**
 * Keeps one network loaded and answers routing requests, one JSON object per line.
 *
 *     benchmark-engine-serve --data data/raptor/france/bench
 *
 * On start it prints {"type":"ready", ...sizes, load time, heap}. Then, for each line read:
 *
 *     {"op":"stops"}                                    -> every stop: [id, name, lat, lon]
 *     {"op":"route","from":[ids],"to":[ids],"time":s,   -> the engine's journeys, each leg
 *      "arriveBy":false,"maxRounds":5}                     with names, times and its path
 *                                                          (maxRounds = most rides = changes + 1)
 *     {"op":"quit"}
 *
 * An endpoint is either stop ids or a point, {"lat":…,"lon":…,"label":"10 Rue …"}: a geocoded
 * address. A point goes to raptor-kmp as Location.Point with Pelo's walking model
 * (WalkingParams.DEFAULT: every stop within 500 m, 4.8 km/h × 1.3 detour, walk-only journey
 * under 1 km). With "fallbackWalkMeters":6000, a point search that finds nothing is run again
 * walking up to that far, keeping journeys that walk no more than that in total: what Pelo does.
 *
 * "ms" in a route answer times the raptor-kmp call alone, not the pipe around it. The first
 * search of each kind (forward, arrive-by) after the round limit changes runs once untimed
 * before the timed run, so "ms" leaves out allocating a search state of the new size. This is
 * what gtfs_bench.explorer, the terminal explorer, talks to.
 */
fun main(args: Array<String>) {
    val values = args.toList().chunked(2).associate { (k, v) -> k.removePrefix("--") to v }
    val data = File(values["data"] ?: error("--data is required"))
    // The console may not be UTF-8 (Windows): write bytes ourselves so stop names survive.
    val out = PrintStream(FileOutputStream(FileDescriptor.out), true, Charsets.UTF_8)

    val started = System.nanoTime()
    val library = RaptorLibrary(File(data, "stops.bin").readBytes(), File(data, "routes.bin").readBytes())
    val period = library.getCurrentPeriod()
    val stops = library.getStops(period)
    val routes = library.getRoutes(period)
    val loadMs = (System.nanoTime() - started) / 1e6
    repeat(2) { System.gc() }
    val heapMb = ManagementFactory.getMemoryMXBean().heapMemoryUsage.used / 1024.0 / 1024.0

    out.println(JsonObject(mapOf(
        "type" to JsonPrimitive("ready"),
        "engine" to JsonPrimitive(object {}.javaClass.getResource("/raptor-kmp.version")?.readText()?.trim() ?: "?"),
        "java" to JsonPrimitive(System.getProperty("java.runtime.version") ?: "?"),
        "stops" to JsonPrimitive(stops.size),
        "routes" to JsonPrimitive(routes.size),
        "trips" to JsonPrimitive(routes.sumOf { it.tripCount.toLong() }),
        "loadMs" to JsonPrimitive(loadMs),
        "heapMb" to JsonPrimitive(heapMb),
    )))

    val states = SearchStates(library)
    val input = System.`in`.bufferedReader(Charsets.UTF_8)
    while (true) {
        val line = input.readLine() ?: break
        if (line.isBlank()) continue
        val answer = try {
            val request = Json.parseToJsonElement(line).jsonObject
            when (request["op"]?.jsonPrimitive?.content) {
                "stops" -> stopsAnswer(stops)
                "route" -> routeAnswer(library, stops, states, request)
                "quit" -> break
                else -> """{"type":"error","message":"unknown op"}"""
            }
        } catch (error: OutOfMemoryError) {
            // A search state is (rounds + 1) × stops × 8 ints: a very high round limit on
            // France does not fit a small heap. Free it and keep serving.
            states.drop()
            System.gc()
            val heapMb = Runtime.getRuntime().maxMemory() / 1024 / 1024
            errorAnswer("OutOfMemoryError: no room for that many rounds in a $heapMb MB heap")
        } catch (error: Exception) {
            errorAnswer(error.toString())
        }
        out.println(answer)
    }
}

private fun errorAnswer(message: String) =
    JsonObject(mapOf("type" to JsonPrimitive("error"), "message" to JsonPrimitive(message))).toString()

/**
 * raptor-kmp 2.2.0 keeps its search state from one call to the next and reuses it whenever it
 * has at least the rounds asked for, but then runs as many rounds as the state has: after a
 * 30-round search, a 5-round one would still explore up to 30 rounds (its journeys stay within
 * 5, its time does not). So when the limit changes, the cached states are dropped and the next
 * search allocates one of the right size. The cache is private, hence reflection; if a later
 * engine renames it, nothing is dropped and [dropping] turns false.
 */
private class SearchStates(private val library: RaptorLibrary) {
    private var rounds = -1
    private val ready = HashSet<Boolean>() // search kinds (arrive-by or not) already run at `rounds`
    var dropping = true
        private set

    /** True when this kind of search has not run at this limit yet: run it once untimed first. */
    fun firstAt(maxRounds: Int, arriveBy: Boolean): Boolean {
        if (maxRounds != rounds) {
            drop()
            rounds = maxRounds
        }
        return ready.add(arriveBy)
    }

    fun drop() {
        ready.clear()
        rounds = -1
        if (!dropping) return
        try {
            val cache = RaptorLibrary::class.java.getDeclaredField("algorithmCache")
                .apply { isAccessible = true }.get(library) as Map<*, *>
            for (algorithm in cache.values.filterNotNull()) {
                for (name in listOf("lastState", "lastBackwardState")) {
                    algorithm.javaClass.getDeclaredField(name).apply { isAccessible = true }.set(algorithm, null)
                }
            }
        } catch (error: ReflectiveOperationException) {
            dropping = false
        }
    }
}

private fun stopsAnswer(stops: List<Stop>): String {
    val text = StringBuilder(stops.size * 48)
    text.append("""{"type":"stops","stops":[""")
    stops.forEachIndexed { i, s ->
        if (i > 0) text.append(',')
        text.append('[').append(s.id).append(',').append(JsonPrimitive(s.name).toString()).append(',')
            .append(s.lat).append(',').append(s.lon).append(']')
    }
    return text.append("]}").toString()
}

/** A route endpoint: stop ids, or a point (an address) and the name to show for it. */
private class Endpoint(val location: Location, val label: String?)

private fun endpoint(element: JsonElement): Endpoint = when (element) {
    is JsonArray -> Endpoint(Location.StopIds(element.map { it.jsonPrimitive.int }), null)
    is JsonObject -> Endpoint(
        Location.Point(element["lat"]!!.jsonPrimitive.double, element["lon"]!!.jsonPrimitive.double),
        element["label"]?.jsonPrimitive?.content,
    )
    else -> error("an endpoint is [stop ids] or {\"lat\":…,\"lon\":…,\"label\":…}")
}

/** Metres walked in a journey, as Pelo counts them: walking seconds at walking speed. */
private fun walkedMeters(legs: List<JourneyLeg>, walking: WalkingParams): Double =
    legs.filter { it.legType != LegType.TRANSIT }.sumOf { (it.arrivalTime - it.departureTime) * walking.speedMetersPerSecond }

private fun routeAnswer(library: RaptorLibrary, stops: List<Stop>, states: SearchStates, request: JsonObject): String {
    val from = endpoint(request["from"]!!)
    val to = endpoint(request["to"]!!)
    val time = request["time"]!!.jsonPrimitive.int
    val arriveBy = request["arriveBy"]?.jsonPrimitive?.boolean ?: false
    val maxRounds = request["maxRounds"]?.jsonPrimitive?.int ?: 5
    val fallbackMeters = request["fallbackWalkMeters"]?.jsonPrimitive?.double
    require(maxRounds >= 1) { "maxRounds must be at least 1" }

    // Two stop sets go through the location overload too: raptor-kmp hands them to the classic
    // stop-id search, so nothing changes for them.
    fun search(walking: WalkingParams) =
        if (arriveBy) library.getOptimizedPathsArriveBy(from.location, to.location, time, maxRounds = maxRounds, walking = walking)
        else library.getOptimizedPaths(from.location, to.location, time, maxRounds = maxRounds, walking = walking)

    val walking = WalkingParams.DEFAULT
    if (states.firstAt(maxRounds, arriveBy)) search(walking)
    val started = System.nanoTime()
    var journeys = search(walking).filter { it.isNotEmpty() }
    var used = walking
    val points = from.location is Location.Point || to.location is Location.Point
    if (journeys.isEmpty() && points && fallbackMeters != null && fallbackMeters > walking.maxAccessEgressDistanceMeters) {
        used = WalkingParams(maxAccessEgressDistanceMeters = fallbackMeters, maxDirectWalkDistanceMeters = fallbackMeters)
        journeys = search(used).filter { it.isNotEmpty() && walkedMeters(it, used) <= fallbackMeters }
    }
    val ms = (System.nanoTime() - started) / 1e6

    val text = StringBuilder()
    text.append("""{"type":"route","ms":""").append(ms)
        .append(""","maxRounds":""").append(maxRounds)
        .append(""","statesDropped":""").append(states.dropping)
        .append(""","walkRadius":""").append(used.maxAccessEgressDistanceMeters)
        .append(""","fallback":""").append(used !== walking)
        .append(""","journeys":[""")
    journeys.forEachIndexed { j, legs ->
        if (j > 0) text.append(',')
        text.append('[')
        legs.forEachIndexed { i, leg -> if (i > 0) text.append(','); appendLeg(text, leg, stops, from.label, to.label) }
        text.append(']')
    }
    return text.append("]}").toString()
}

/**
 * One leg as JSON. Stop index -1 is a point endpoint (an address): its name is the label the
 * request gave, its position the coordinates raptor-kmp puts on walk legs.
 */
private fun appendLeg(text: StringBuilder, leg: JourneyLeg, stops: List<Stop>, fromLabel: String?, toLabel: String?) {
    fun stop(i: Int) = stops.getOrNull(i)
    fun name(i: Int, label: String?) = if (i == -1) label ?: "Adresse" else stop(i)?.name ?: "?"
    fun point(i: Int) = stop(i)?.let { "[${it.lat},${it.lon}]" }
    fun coordinate(lat: Double?, lon: Double?) = if (lat != null && lon != null) "[$lat,$lon]" else null
    val path = buildList {
        add(if (leg.fromStopIndex == -1) coordinate(leg.fromLat, leg.fromLon) else point(leg.fromStopIndex))
        leg.intermediateStopIndices.forEach { add(point(it)) }
        add(if (leg.toStopIndex == -1) coordinate(leg.toLat, leg.toLon) else point(leg.toStopIndex))
    }.filterNotNull()
    text.append('{')
        .append("\"from\":").append(JsonPrimitive(name(leg.fromStopIndex, fromLabel)).toString())
        .append(",\"to\":").append(JsonPrimitive(name(leg.toStopIndex, toLabel)).toString())
        .append(",\"dep\":").append(leg.departureTime)
        .append(",\"arr\":").append(leg.arrivalTime)
        .append(",\"route\":").append(leg.routeName?.let { JsonPrimitive(it).toString() } ?: "null")
        .append(",\"direction\":").append(leg.direction?.let { JsonPrimitive(it).toString() } ?: "null")
        .append(",\"walk\":").append(leg.isTransfer)
        .append(",\"kind\":\"").append(leg.legType.name.lowercase()).append('"')
        .append(",\"stops\":").append(leg.intermediateStopIndices.size)
        .append(",\"path\":[").append(path.joinToString(",")).append("]}")
}
