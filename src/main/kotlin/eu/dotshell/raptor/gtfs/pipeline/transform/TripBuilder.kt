package eu.dotshell.raptor.gtfs.pipeline.transform

import eu.dotshell.raptor.gtfs.pipeline.gtfs.GTFSReader
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.*

object TripBuilder {
    fun buildAndSortTrips(reader: GTFSReader, routes: List<RouteData>, allowPartial: Boolean = false) {
        println("Building and sorting trips")

        val tripsByRoute = reader.tripsData.groupBy { it.routeId }
        val stopTimesByTripInternal = reader.stopTimesData.groupBy { it.tripIdInternal }
        var totalTrips = 0

        for (route in routes) {
            val routeTrips = tripsByRoute[route.routeIdGtfs] ?: continue
            val intToGtfs = routeTrips.associate { it.tripIdInternal to it.tripId }

            val tripDataList = mutableListOf<Pair<Float, TripData>>()

            for (trip in routeTrips) {
                val stList = stopTimesByTripInternal[trip.tripIdInternal] ?: continue
                if (stList.isEmpty()) continue

                val arrivalMap = stList.associate { it.stopIdInternal to it.arrivalTime.toFloat() }
                val arrivalTimes = route.stopIds.map { arrivalMap[it] ?: Float.POSITIVE_INFINITY }
                val isPartial = arrivalTimes.any { it.isInfinite() }

                if (isPartial && !allowPartial) continue

                val firstTime = arrivalTimes.firstOrNull() ?: Float.POSITIVE_INFINITY
                val tripData = TripData(
                    tripIdInternal = trip.tripIdInternal,
                    tripIdGtfs = intToGtfs[trip.tripIdInternal] ?: "",
                    arrivalTimes = arrivalTimes,
                    isPartial = isPartial
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
