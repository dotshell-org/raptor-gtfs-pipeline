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
