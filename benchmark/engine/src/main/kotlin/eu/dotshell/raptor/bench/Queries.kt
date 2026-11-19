package eu.dotshell.raptor.bench

import io.raptor.model.Stop
import java.io.File
import java.util.Random
import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

/** One query: origin and destination stop sets, and a time (departure or arrival), seconds. */
data class Query(val origins: List<Int>, val destinations: List<Int>, val time: Int)

fun distanceMeters(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
    val dLat = Math.toRadians(lat2 - lat1)
    val dLon = Math.toRadians(lon2 - lon1)
    val a = sin(dLat / 2).pow(2) + cos(Math.toRadians(lat1)) * cos(Math.toRadians(lat2)) * sin(dLon / 2).pow(2)
    return 2 * 6_371_000.0 * asin(sqrt(a))
}

/**
 * Stops by position, on a grid of ~1 km cells: answers "every stop within r metres" without
 * scanning the 300 000 stops of France for each point.
 */
class StopIndex(private val stops: List<Stop>) {
    private val cell = 0.01  // degrees, about 1.1 km north-south
    private val grid = HashMap<Long, MutableList<Int>>()

    init {
        stops.forEachIndexed { i, s -> grid.getOrPut(key(s.lat, s.lon)) { mutableListOf() }.add(i) }
    }

    private fun cellOf(value: Double): Long = Math.floor(value / cell).toLong()

    private fun key(lat: Double, lon: Double): Long = (cellOf(lat) shl 32) xor (cellOf(lon) and 0xffffffffL)

    /** The closest stop within [radius] metres, or null. */
    fun nearest(lat: Double, lon: Double, radius: Double = 2_000.0): Stop? =
        within(lat, lon, radius).minByOrNull { distanceMeters(lat, lon, it.lat, it.lon) }

    fun within(lat: Double, lon: Double, radius: Double): List<Stop> {
        val reach = (radius / 1_000.0 / (cell * 111.0)).toInt() + 1
        val baseLat = cellOf(lat)
        val baseLon = cellOf(lon)
        val found = ArrayList<Stop>()
        for (dy in -reach..reach) for (dx in -reach..reach) {
            val k = ((baseLat + dy) shl 32) xor ((baseLon + dx) and 0xffffffffL)
            grid[k]?.forEach { i ->
                val s = stops[i]
                if (distanceMeters(lat, lon, s.lat, s.lon) <= radius) found.add(s)
            }
        }
        return found
    }
}

/** Uniform pairs over every stop, as raptor-kmp's RandomQueryGenerator: departures 6:00–21:59. */
fun randomQueries(stopIds: List<Int>, count: Int, seed: Long): List<Query> {
    val rng = Random(seed)
    return List(count) {
        val o = rng.nextInt(stopIds.size)
        var d = rng.nextInt(stopIds.size)
        if (d == o) d = (d + 1) % stopIds.size
        Query(listOf(stopIds[o]), listOf(stopIds[d]), (6 + rng.nextInt(16)) * 3600 + rng.nextInt(60) * 60)
    }
}

/** A trip between two points (addresses) rather than stops, and a time. */
data class PointQuery(val oLat: Double, val oLon: Double, val dLat: Double, val dLon: Double, val time: Int)

/** A point at most [meters] from (lat, lon), uniform over the disc. */
private fun jittered(rng: Random, lat: Double, lon: Double, meters: Double): Pair<Double, Double> {
    val r = meters * sqrt(rng.nextDouble())
    val angle = rng.nextDouble() * 2 * Math.PI
    val dLat = r * cos(angle) / 111_320.0
    val dLon = r * sin(angle) / (111_320.0 * cos(Math.toRadians(lat)))
    return Pair(lat + dLat, lon + dLon)
}

/**
 * [randomQueries]' pairs turned into addresses: each stop moved up to [jitter] metres in a
 * random direction, as an address near a stop is. Same stops and times as the random set.
 */
fun randomPoints(stops: List<Stop>, count: Int, seed: Long, jitter: Double = 300.0): List<PointQuery> {
    val byId = stops.associateBy { it.id }
    val rng = Random(seed xor 0x5EEDL)
    return randomQueries(stops.map { it.id }, count, seed).map { q ->
        val o = byId.getValue(q.origins.single())
        val d = byId.getValue(q.destinations.single())
        val (oLat, oLon) = jittered(rng, o.lat, o.lon, jitter)
        val (dLat, dLon) = jittered(rng, d.lat, d.lon, jitter)
        PointQuery(oLat, oLon, dLat, dLon, q.time)
    }
}

/** The very points [localQueries] draws (same seed, same draws), kept as points. */
fun localPoints(area: Area, index: StopIndex, seed: Long, radius: Double = 400.0): List<PointQuery>? {
    val rng = Random(seed xor area.name.hashCode().toLong())
    val points = ArrayList<PointQuery>()
    var misses = 0
    fun point() = Pair(area.latMin + rng.nextDouble() * (area.latMax - area.latMin), area.lonMin + rng.nextDouble() * (area.lonMax - area.lonMin))
    while (points.size < area.pairs) {
        val (oLat, oLon) = point()
        val (dLat, dLon) = point()
        val time = (6 + rng.nextInt(16)) * 3600 + rng.nextInt(60) * 60
        val km = distanceMeters(oLat, oLon, dLat, dLon) / 1_000.0
        if (km < area.minKm || km > area.maxKm) continue
        if (index.within(oLat, oLon, radius).isEmpty() || index.within(dLat, dLon, radius).isEmpty()) {
            if (++misses > area.pairs * 20) return null
            continue
        }
        points.add(PointQuery(oLat, oLon, dLat, dLon, time))
    }
    return points
}

/** A city's box, where the same seeded trips are drawn for every tier that covers it. */
data class Area(
    val name: String, val latMin: Double, val latMax: Double, val lonMin: Double, val lonMax: Double,
    val pairs: Int, val minKm: Double, val maxKm: Double,
)

fun readAreas(file: File): List<Area> = file.readLines().drop(1).filter { it.isNotBlank() && !it.startsWith("#") }.map {
    val c = it.split(",")
    Area(c[0], c[1].toDouble(), c[2].toDouble(), c[3].toDouble(), c[4].toDouble(), c[5].toInt(), c[6].toDouble(), c[7].toDouble())
}

/**
 * Seeded points drawn in the area, each resolved to every stop within `radius` metres. The
 * points depend only on the area and the seed, so every tier replays the same trips on its
 * own network. Returns null when the tier does not cover the area (most points find no stop).
 */
fun localQueries(area: Area, index: StopIndex, seed: Long, radius: Double = 400.0): List<Query>? {
    val rng = Random(seed xor area.name.hashCode().toLong())
    val queries = ArrayList<Query>()
    var misses = 0
    fun point() = Pair(area.latMin + rng.nextDouble() * (area.latMax - area.latMin), area.lonMin + rng.nextDouble() * (area.lonMax - area.lonMin))
    while (queries.size < area.pairs) {
        val (oLat, oLon) = point()
        val (dLat, dLon) = point()
        val time = (6 + rng.nextInt(16)) * 3600 + rng.nextInt(60) * 60
        val km = distanceMeters(oLat, oLon, dLat, dLon) / 1_000.0
        if (km < area.minKm || km > area.maxKm) continue
        val o = index.within(oLat, oLon, radius).map { it.id }
        val d = index.within(dLat, dLon, radius).map { it.id }
        if (o.isEmpty() || d.isEmpty()) {
            if (++misses > area.pairs * 20) return null
            continue
        }
        queries.add(Query(o, d, time))
    }
    return queries
}

/** A named trip between two places, each place being every stop within radius metres. */
data class NamedTrip(
    val name: String, val kind: String, val oLat: Double, val oLon: Double, val dLat: Double, val dLon: Double,
    val radius: Double, val departure: Int,
)

fun readScenarios(file: File): List<NamedTrip> = file.readLines().drop(1).filter { it.isNotBlank() && !it.startsWith("#") }.map {
    val c = it.split(",")
    val (h, m) = c[7].split(":").map(String::toInt)
    NamedTrip(c[0], c[1], c[2].toDouble(), c[3].toDouble(), c[4].toDouble(), c[5].toDouble(), c[6].toDouble(), h * 3600 + m * 60)
}

fun hhmm(seconds: Int): String = "%02d:%02d".format(seconds / 3600, (seconds % 3600) / 60)
