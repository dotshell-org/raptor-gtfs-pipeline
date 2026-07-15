package com.raptor.transform

import com.raptor.gtfs.GTFSReader
import com.raptor.gtfs.models.*
import kotlin.math.*

object TripBuilder {
    fun buildAndSortTrips(reader: GTFSReader, routes: List<RouteData>, allowPartial: Boolean = false) {
        println("Building and sorting trips")

        val tripsByRoute = reader.tripsData.groupBy { it.route_id }
        val stopTimesByTripInternal = reader.stopTimesData.groupBy { it.trip_id_internal }
        var totalTrips = 0

        for (route in routes) {
            val routeTrips = tripsByRoute[route.route_id_gtfs] ?: continue
            val intToGtfs = routeTrips.associate { it.trip_id_internal to it.trip_id }

            val tripDataList = mutableListOf<Pair<Float, TripData>>()

            for (trip in routeTrips) {
                val stList = stopTimesByTripInternal[trip.trip_id_internal] ?: continue
                if (stList.isEmpty()) continue

                val arrivalMap = stList.associate { it.stop_id_internal to it.arrival_time.toFloat() }
                val arrivalTimes = route.stop_ids.map { arrivalMap[it] ?: Float.POSITIVE_INFINITY }
                val isPartial = arrivalTimes.any { it.isInfinite() }

                if (isPartial && !allowPartial) continue

                val firstTime = arrivalTimes.firstOrNull() ?: Float.POSITIVE_INFINITY
                val tripData = TripData(
                    trip_id_internal = trip.trip_id_internal,
                    trip_id_gtfs = intToGtfs[trip.trip_id_internal] ?: "",
                    arrival_times = arrivalTimes,
                    is_partial = isPartial
                )
                tripDataList.add(Pair(firstTime, tripData))
            }

            tripDataList.sortBy { it.first }
            route.trips.addAll(tripDataList.map { it.second })
            totalTrips += route.trips.size
        }

        println("Built $totalTrips trips across ${routes.size} routes")
    }
}
