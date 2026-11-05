package eu.dotshell.raptor.gtfs.pipeline.transform

import eu.dotshell.raptor.gtfs.pipeline.PipelineLog
import eu.dotshell.raptor.gtfs.pipeline.gtfs.GTFSReader
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.*

object TripBuilder {
    fun buildAndSortTrips(reader: GTFSReader, routes: List<RouteData>) {
        PipelineLog.info("Building and sorting trips")

        val stopTimesByTrip = reader.stopTimesData
            .groupBy { it.tripIdInternal }
            .mapValues { (_, times) -> times.sortedBy { it.stopSequence } }

        /*
         * A trip belongs to the one route of its line, its direction and its exact stop sequence.
         *
         * Grouping on the GTFS route id alone offered every trip of a line to both of its
         * direction-routes. Wherever the two directions call at the same stops — a two-stop
         * funicular, a terminal loop, a line whose return is a subset of its outward journey — the
         * return trip mapped cleanly onto the outward stop order and was written into both.
         *
         * That produced duplicate trips (2 082 of them in one TCL weekday period) and, worse,
         * timetables that run backwards: a descent recorded against the ascending stop order, which
         * a router reads as a vehicle arriving before it left.
         *
         * Matching the whole sequence also gives each call its own time where a sequence visits a
         * stop twice — a terminal loop, an out-and-back branch.
         */
        val tripsByPattern = reader.tripsData.groupBy { trip ->
            val stops = stopTimesByTrip[trip.tripIdInternal].orEmpty().map { it.stopIdInternal }
            Triple(trip.routeId, trip.directionId, stops)
        }

        var totalTrips = 0
        for (route in routes) {
            val routeTrips = tripsByPattern[Triple(route.routeIdGtfs, route.directionId, route.stopIds)] ?: continue

            val tripDataList = routeTrips.map { trip ->
                TripData(
                    tripIdInternal = trip.tripIdInternal,
                    tripIdGtfs = trip.tripId,
                    arrivalTimes = stopTimesByTrip.getValue(trip.tripIdInternal).map { it.arrivalTime.toFloat() },
                    isPartial = false
                )
            }

            route.trips.addAll(tripDataList.sortedBy { it.arrivalTimes.first() })
            totalTrips += route.trips.size
        }

        PipelineLog.info("Built $totalTrips trips across ${routes.size} routes")
    }
}
