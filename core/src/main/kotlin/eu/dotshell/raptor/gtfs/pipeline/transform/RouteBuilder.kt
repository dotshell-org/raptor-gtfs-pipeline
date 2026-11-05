package eu.dotshell.raptor.gtfs.pipeline.transform

import eu.dotshell.raptor.gtfs.pipeline.PipelineLog
import eu.dotshell.raptor.gtfs.pipeline.gtfs.GTFSReader
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.*

object RouteBuilder {
    /**
     * One route per stop sequence a line runs in a direction, the most-run sequence first.
     *
     * A RAPTOR route is one stop sequence with a full timetable, so a trip skipping a stop of it or
     * calling somewhere else cannot be written into it. There used to be a single route per
     * direction, and every trip that did not cover its whole sequence was dropped: half of line 1
     * of the Mistral export on any day, and on Sundays all of lines U, 18, 72 and 81, whose Sunday
     * service follows another route than the weekday one that set the sequence.
     *
     * The binary has no direction field, so consumers have to tell directions apart from the stops
     * themselves. Keeping the most-run sequence first gives them a stable main pattern to start from.
     */
    fun buildRoutes(reader: GTFSReader): List<RouteData> {
        PipelineLog.info("Building routes, one per stop sequence")

        val tripSequences = reader.stopTimesData
            .groupBy { it.tripId }
            .mapValues { (_, times) -> times.sortedBy { it.stopSequence }.map { it.stopId } }

        val routeNameLookup = reader.routes.associate {
            it.routeId to it.routeShortName.ifBlank { it.routeLongName }
        }

        val tripsByRouteDir = reader.tripsData
            .groupBy { Pair(it.routeId, it.directionId) }
            .mapValues { (_, trips) -> trips.map { it.tripId } }

        val routes = mutableListOf<RouteData>()

        for ((key, tripIds) in tripsByRouteDir.entries.sortedBy { it.key.first + "_" + it.key.second }) {
            val (routeId, directionId) = key
            val routeIdInternal = reader.routeIdMap[routeId] ?: continue

            val sequencesForRoute = tripIds.mapNotNull { tripSequences[it] }
            if (sequencesForRoute.isEmpty()) continue

            for (sequence in sequencesByUse(sequencesForRoute)) {
                routes.add(RouteData(
                    routeIdInternal = routeIdInternal,
                    routeIdGtfs = routeId,
                    routeName = routeNameLookup[routeId] ?: "",
                    directionId = directionId,
                    stopIds = sequence.mapNotNull { reader.stopIdMap[it] },
                    trips = mutableListOf()
                ))
            }
        }

        PipelineLog.info("Built ${routes.size} routes")
        return routes
    }

    /** Every distinct sequence, most trips first; ties broken on the stops, so builds are repeatable. */
    private fun sequencesByUse(sequences: List<List<String>>): List<List<String>> =
        sequences.groupingBy { it }.eachCount().entries
            .sortedWith(compareByDescending<Map.Entry<List<String>, Int>> { it.value }.thenBy { it.key.joinToString(",") })
            .map { it.key }
}
