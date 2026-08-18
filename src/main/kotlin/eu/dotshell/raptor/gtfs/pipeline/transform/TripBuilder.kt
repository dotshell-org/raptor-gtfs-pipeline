package eu.dotshell.raptor.gtfs.pipeline.transform

import eu.dotshell.raptor.gtfs.pipeline.gtfs.GTFSReader
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.*

object TripBuilder {
    fun buildAndSortTrips(reader: GTFSReader, routes: List<RouteData>, allowPartial: Boolean = false) {
        println("Building and sorting trips")

        /*
         * Trips belong to a route *and a direction*.
         *
         * Grouping on the GTFS route id alone offered every trip of a line to both of its
         * direction-routes. Most were rejected for lacking a time at some stop of the sequence they
         * did not serve, but wherever the two directions call at the same stops — a two-stop
         * funicular, a terminal loop, a line whose return is a subset of its outward journey — the
         * return trip mapped cleanly onto the outward stop order and was written into both.
         *
         * That produced duplicate trips (2 082 of them in one TCL weekday period) and, worse,
         * timetables that run backwards: a descent recorded against the ascending stop order, which
         * a router reads as a vehicle arriving before it left.
         */
        val tripsByRouteDir = reader.tripsData.groupBy { Pair(it.routeId, it.directionId) }
        val stopTimesByTripInternal = reader.stopTimesData.groupBy { it.tripIdInternal }
        var totalTrips = 0

        for (route in routes) {
            val routeTrips = tripsByRouteDir[Pair(route.routeIdGtfs, route.directionId)] ?: continue
            val intToGtfs = routeTrips.associate { it.tripIdInternal to it.tripId }

            val tripDataList = mutableListOf<Pair<Float, TripData>>()

            for (trip in routeTrips) {
                val stList = stopTimesByTripInternal[trip.tripIdInternal] ?: continue
                if (stList.isEmpty()) continue

                /*
                 * Times are matched by position along the journey, not by stop id.
                 *
                 * A canonical sequence can call at the same stop twice — a terminal loop, an
                 * out-and-back branch — and a map keyed by stop id holds one time per stop, so both
                 * calls received the same one. Where the surviving time was the earlier visit, the
                 * second call read as arriving before the first: a timetable running backwards.
                 *
                 * Walking both sequences in order gives each call its own time. A stop the trip
                 * does not serve leaves a gap and the trip is dropped as partial, as before.
                 */
                val ordered = stList.sortedBy { it.stopSequence }
                val arrivalTimes = MutableList(route.stopIds.size) { Float.POSITIVE_INFINITY }
                var cursor = 0
                for ((position, stopId) in route.stopIds.withIndex()) {
                    var scan = cursor
                    while (scan < ordered.size && ordered[scan].stopIdInternal != stopId) scan++
                    if (scan < ordered.size) {
                        arrivalTimes[position] = ordered[scan].arrivalTime.toFloat()
                        cursor = scan + 1
                    }
                }
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
