package com.raptor.transform

import com.raptor.gtfs.GTFSReader
import com.raptor.gtfs.models.*
import kotlin.math.*

object StopBuilder {
    fun buildStops(reader: GTFSReader, routes: List<RouteData>): List<StopData> {
        println("Building stop data with route references")

        val stopToRoutes = mutableMapOf<Int, MutableSet<Int>>()
        for (route in routes) {
            val routeId = route.route_id_internal
            for (stopId in route.stop_ids) {
                stopToRoutes.computeIfAbsent(stopId) { mutableSetOf() }.add(routeId)
            }
        }

        val stops = mutableListOf<StopData>()
        for (stop in reader.stops) {
            val stopIdInternal = reader.stopIdMap[stop.stop_id] ?: continue
            val routeIds = stopToRoutes[stopIdInternal]?.sorted()?.toMutableList() ?: mutableListOf()

            stops.add(StopData(
                stop_id_internal = stopIdInternal,
                stop_id_gtfs = stop.stop_id,
                name = stop.name,
                lat = stop.lat,
                lon = stop.lon,
                route_ids = routeIds,
                transfers = mutableListOf()
            ))
        }

        println("Built ${stops.size} stops")
        return stops
    }
}
