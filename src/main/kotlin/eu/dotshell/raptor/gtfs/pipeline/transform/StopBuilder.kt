package eu.dotshell.raptor.gtfs.pipeline.transform

import eu.dotshell.raptor.gtfs.pipeline.gtfs.GTFSReader
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.*

object StopBuilder {
    fun buildStops(reader: GTFSReader, routes: List<RouteData>): List<StopData> {
        println("Building stop data with route references")

        val stopToRoutes = mutableMapOf<Int, MutableSet<Int>>()
        for (route in routes) {
            val routeId = route.routeIdInternal
            for (stopId in route.stopIds) {
                stopToRoutes.computeIfAbsent(stopId) { mutableSetOf() }.add(routeId)
            }
        }

        val stops = mutableListOf<StopData>()
        for (stop in reader.stops) {
            val stopIdInternal = reader.stopIdMap[stop.stopId] ?: continue
            val routeIds = stopToRoutes[stopIdInternal]?.sorted()?.toMutableList() ?: mutableListOf()

            stops.add(StopData(
                stopIdInternal = stopIdInternal,
                stopIdGtfs = stop.stopId,
                name = stop.name,
                lat = stop.lat,
                lon = stop.lon,
                zone = stop.zoneId,
                routeIds = routeIds,
                transfers = mutableListOf()
            ))
        }

        println("Built ${stops.size} stops")
        return stops
    }
}
