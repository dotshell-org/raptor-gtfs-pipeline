package eu.dotshell.raptor.gtfs.pipeline.transform

import eu.dotshell.raptor.gtfs.pipeline.gtfs.GTFSReader
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.*

object LineGeometryBuilder {
    fun buildLines(reader: GTFSReader): List<LineData> {
        if (reader.shapesPoints.isEmpty() || reader.tripsData.isEmpty()) {
            return emptyList()
        }

        val grouped = reader.tripsData
            .filter { it.shapeId.isNotEmpty() }
            .groupBy( { Pair(it.routeId, it.directionId) }, { it.shapeId } )
            .mapValues { (_, ids) -> ids.distinct() }

        val shapesByRoute = mutableMapOf<String, MutableMap<Int, List<String>>>()
        for ((key, shapeIds) in grouped) {
            val (routeId, directionId) = key
            shapesByRoute.computeIfAbsent(routeId) { mutableMapOf() }[directionId] = shapeIds
        }

        val lines = mutableListOf<LineData>()
        for (route in reader.routes) {
            val perDirection = shapesByRoute[route.routeId] ?: continue
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

            val name = route.routeShortName.ifBlank { route.routeLongName }.ifBlank { route.routeId }
            val routeIdInternal = reader.routeIdMap[route.routeId] ?: continue

            lines.add(LineData(
                lineIdInternal = routeIdInternal,
                name = name,
                transportType = route.routeType,
                color = route.routeColor,
                textColor = route.routeTextColor,
                paths = paths
            ))
        }

        println("Built geometry for ${lines.size} lines")
        return lines
    }
}
