package eu.dotshell.raptor.gtfs.pipeline.transform

import eu.dotshell.raptor.gtfs.pipeline.PipelineLog
import eu.dotshell.raptor.gtfs.pipeline.gtfs.GTFSReader
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.*

object TripBuilder {
    /**
     * Fills [routes] with their trips, earliest first, for the layout [RouteBuilder] built them in:
     * [routePerStopSequence] must be the same value.
     */
    fun buildAndSortTrips(reader: GTFSReader, routes: List<RouteData>, routePerStopSequence: Boolean = false) {
        PipelineLog.info("Building and sorting trips")
        if (routePerStopSequence) buildByStopSequence(reader, routes) else buildByDirection(reader, routes)
    }

    /**
     * A trip belongs to the one route of its line, its direction and its exact stop sequence.
     *
     * Matching the whole sequence also gives each call its own time where a sequence visits a stop
     * twice — a terminal loop, an out-and-back branch.
     */
    private fun buildByStopSequence(reader: GTFSReader, routes: List<RouteData>) {
        val stopTimesByTrip = reader.stopTimesData
            .groupBy { it.tripIdInternal }
            .mapValues { (_, times) -> times.sortedBy { it.stopSequence } }

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

    /**
     * A trip belongs to the route of its line and direction, and is dropped unless it calls at every
     * stop of that route's sequence. This is 0.4.0's behaviour, kept as the default layout.
     *
     * Trips belong to a route *and a direction*: grouping on the GTFS route id alone offered every
     * trip of a line to both of its direction-routes. Wherever the two directions call at the same
     * stops — a two-stop funicular, a terminal loop, a line whose return is a subset of its outward
     * journey — the return trip mapped cleanly onto the outward stop order and was written into
     * both. That produced duplicate trips (2 082 of them in one TCL weekday period) and, worse,
     * timetables that run backwards: a descent recorded against the ascending stop order, which a
     * router reads as a vehicle arriving before it left.
     */
    private fun buildByDirection(reader: GTFSReader, routes: List<RouteData>) {
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
                 * does not serve leaves a gap and the trip is dropped as partial.
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
                if (arrivalTimes.any { it.isInfinite() }) continue

                val tripData = TripData(
                    tripIdInternal = trip.tripIdInternal,
                    tripIdGtfs = intToGtfs[trip.tripIdInternal] ?: "",
                    arrivalTimes = arrivalTimes,
                    isPartial = false
                )
                tripDataList.add(Pair(arrivalTimes.firstOrNull() ?: Float.POSITIVE_INFINITY, tripData))
            }

            tripDataList.sortBy { it.first }

            route.trips.addAll(tripDataList.map { it.second })
            totalTrips += route.trips.size
        }

        PipelineLog.info("Built $totalTrips trips across ${routes.size} routes")
    }
}
