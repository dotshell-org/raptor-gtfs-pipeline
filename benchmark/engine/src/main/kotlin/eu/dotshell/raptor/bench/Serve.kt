package eu.dotshell.raptor.bench

import io.raptor.RaptorLibrary
import io.raptor.core.JourneyLeg
import io.raptor.model.Stop
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
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
 *     {"op":"quit"}
 *
 * "ms" in a route answer times the raptor-kmp call alone, not the pipe around it. This is
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

    val input = System.`in`.bufferedReader(Charsets.UTF_8)
    while (true) {
        val line = input.readLine() ?: break
        if (line.isBlank()) continue
        val answer = try {
            val request = Json.parseToJsonElement(line).jsonObject
            when (request["op"]?.jsonPrimitive?.content) {
                "stops" -> stopsAnswer(stops)
                "route" -> routeAnswer(library, stops, request)
                "quit" -> break
                else -> """{"type":"error","message":"unknown op"}"""
            }
        } catch (error: Exception) {
            JsonObject(mapOf("type" to JsonPrimitive("error"), "message" to JsonPrimitive(error.toString()))).toString()
        }
        out.println(answer)
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

private fun routeAnswer(library: RaptorLibrary, stops: List<Stop>, request: JsonObject): String {
    val from = request["from"]!!.jsonArray.map { it.jsonPrimitive.int }
    val to = request["to"]!!.jsonArray.map { it.jsonPrimitive.int }
    val time = request["time"]!!.jsonPrimitive.int
    val arriveBy = request["arriveBy"]?.jsonPrimitive?.boolean ?: false
    val maxRounds = request["maxRounds"]?.jsonPrimitive?.int ?: 5

    val started = System.nanoTime()
    val journeys = if (arriveBy) library.getOptimizedPathsArriveBy(from, to, time, maxRounds = maxRounds)
                   else library.getOptimizedPaths(from, to, time, maxRounds = maxRounds)
    val ms = (System.nanoTime() - started) / 1e6

    val text = StringBuilder()
    text.append("""{"type":"route","ms":""").append(ms).append(""","journeys":[""")
    journeys.filter { it.isNotEmpty() }.forEachIndexed { j, legs ->
        if (j > 0) text.append(',')
        text.append('[')
        legs.forEachIndexed { i, leg -> if (i > 0) text.append(','); appendLeg(text, leg, stops) }
        text.append(']')
    }
    return text.append("]}").toString()
}

private fun appendLeg(text: StringBuilder, leg: JourneyLeg, stops: List<Stop>) {
    fun stop(i: Int) = stops.getOrNull(i)
    fun point(i: Int) = stop(i)?.let { "[${it.lat},${it.lon}]" }
    val path = (listOf(leg.fromStopIndex) + leg.intermediateStopIndices + listOf(leg.toStopIndex)).mapNotNull(::point)
    text.append('{')
        .append("\"from\":").append(JsonPrimitive(stop(leg.fromStopIndex)?.name ?: "?").toString())
        .append(",\"to\":").append(JsonPrimitive(stop(leg.toStopIndex)?.name ?: "?").toString())
        .append(",\"dep\":").append(leg.departureTime)
        .append(",\"arr\":").append(leg.arrivalTime)
        .append(",\"route\":").append(leg.routeName?.let { JsonPrimitive(it).toString() } ?: "null")
        .append(",\"direction\":").append(leg.direction?.let { JsonPrimitive(it).toString() } ?: "null")
        .append(",\"walk\":").append(leg.isTransfer)
        .append(",\"stops\":").append(leg.intermediateStopIndices.size)
        .append(",\"path\":[").append(path.joinToString(",")).append("]}")
}
