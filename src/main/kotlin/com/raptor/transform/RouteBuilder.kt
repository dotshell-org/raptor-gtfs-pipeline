package com.raptor.transform

import com.raptor.gtfs.GTFSReader
import com.raptor.gtfs.models.*
import kotlin.math.*

object RouteBuilder {
    fun buildRoutes(reader: GTFSReader): List<RouteData> {
        println("Building routes with canonical stop sequences")

        val tripSequences = reader.stopTimesData
            .groupBy { it.trip_id }
            .mapValues { (_, times) -> times.map { it.stop_id } }

        val routeNameLookup = reader.routes.associate {
            it.route_id to it.route_short_name.ifBlank { it.route_long_name }
        }

        val tripsByRouteDir = reader.tripsData
            .groupBy { Pair(it.route_id, it.direction_id) }
            .mapValues { (_, trips) -> trips.map { it.trip_id } }

        val routes = mutableListOf<RouteData>()

        for ((key, tripIds) in tripsByRouteDir.entries.sortedBy { it.key.first + "_" + it.key.second }) {
            val (routeId, directionId) = key
            val routeIdInternal = reader.routeIdMap[routeId] ?: continue

            val sequencesForRoute = tripIds.mapNotNull { tripSequences[it] }
            if (sequencesForRoute.isEmpty()) continue

            val canonicalSeq = findCanonicalSequence(sequencesForRoute, "${routeId}_dir$directionId")
            val canonicalStopIds = canonicalSeq.mapNotNull { reader.stopIdMap[it] }

            routes.add(RouteData(
                route_id_internal = routeIdInternal,
                route_id_gtfs = routeId,
                route_name = routeNameLookup[routeId] ?: "",
                stop_ids = canonicalStopIds,
                trips = mutableListOf()
            ))
        }

        println("Built ${routes.size} routes")
        return routes
    }

    private fun findCanonicalSequence(sequences: List<List<String>>, routeId: String): List<String> {
        if (sequences.isEmpty()) throw IllegalArgumentException("Route $routeId has no sequences")

        val counter = sequences.groupingBy { it }.eachCount()
        val maxCount = counter.values.maxOrNull() ?: 0
        val tiedSequences = counter.filterValues { it == maxCount }.keys.toList()

        return if (tiedSequences.size > 1) {
            tiedSequences.minByOrNull { it.joinToString(",") } ?: tiedSequences.first()
        } else {
            tiedSequences.first()
        }
    }
}
