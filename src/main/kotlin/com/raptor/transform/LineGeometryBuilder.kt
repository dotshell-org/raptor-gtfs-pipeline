package com.raptor.transform

import com.raptor.gtfs.GTFSReader
import com.raptor.gtfs.models.*
import kotlin.math.*

object LineGeometryBuilder {
    fun buildLines(reader: GTFSReader): List<LineData> {
        if (reader.shapesPoints.isEmpty() || reader.tripsData.isEmpty()) {
            return emptyList()
        }

        val grouped = reader.tripsData
            .filter { it.shape_id.isNotEmpty() }
            .groupBy( { Pair(it.route_id, it.direction_id) }, { it.shape_id } )
            .mapValues { (_, ids) -> ids.distinct() }

        val shapesByRoute = mutableMapOf<String, MutableMap<Int, List<String>>>()
        for ((key, shapeIds) in grouped) {
            val (routeId, directionId) = key
            shapesByRoute.computeIfAbsent(routeId) { mutableMapOf() }[directionId] = shapeIds
        }

        val lines = mutableListOf<LineData>()
        for (route in reader.routes) {
            val perDirection = shapesByRoute[route.route_id] ?: continue
            val paths = mutableListOf<LinePath>()

            for ((directionId, shapeIds) in perDirection.toSortedMap()) {
                var bestPoints: List<Pair<Double, Double>>? = null
                for (shapeId in shapeIds) {
                    val points = reader.shapesPoints[shapeId]
                    if (points != null && (bestPoints == null || points.size > bestPoints.size)) {
                        bestPoints = points
                    }
                }
                if (bestPoints != null) {
                    paths.add(LinePath(directionId, bestPoints.toMutableList()))
                }
            }

            if (paths.isEmpty()) continue

            val name = route.route_short_name.ifBlank { route.route_long_name }.ifBlank { route.route_id }
            val routeIdInternal = reader.routeIdMap[route.route_id] ?: continue

            lines.add(LineData(
                line_id_internal = routeIdInternal,
                name = name,
                transport_type = route.route_type,
                color = route.route_color,
                text_color = route.route_text_color,
                paths = paths
            ))
        }

        println("Built geometry for ${lines.size} lines")
        return lines
    }
}
