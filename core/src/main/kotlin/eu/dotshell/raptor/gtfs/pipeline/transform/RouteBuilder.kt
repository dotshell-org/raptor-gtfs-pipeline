package eu.dotshell.raptor.gtfs.pipeline.transform

import eu.dotshell.raptor.gtfs.pipeline.PipelineLog
import eu.dotshell.raptor.gtfs.pipeline.gtfs.GTFSReader
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.*

object RouteBuilder {
    /**
     * The RAPTOR routes of the feed, in one of two layouts.
     *
     * By default, one route per line direction, with the most-run stop sequence; [TripBuilder]
     * then drops every trip that does not cover that whole sequence. Clients may read a line's
     * routes as its directions, which is what apps built before 0.5.0 do.
     *
     * With [routePerStopSequence], one route per stop sequence a line runs in a direction, the
     * most-run sequence first. A RAPTOR route is one stop sequence with a full timetable, so the
     * default cannot hold a trip that skips a stop or calls elsewhere: on the Mistral export of
     * November 2026 it lost half of line 1 on any day, and on Sundays all of lines U, 18, 72 and
     * 81, whose Sunday service follows another route than the weekday one. The binary has no
     * direction field, so consumers then have to tell directions apart from the stops themselves;
     * keeping the most-run sequence first gives them a stable main pattern to start from.
     *
     * The layout is chosen per profile (`options.route_per_stop_sequence`): a city may switch
     * only once its installed apps tell directions apart from the stops.
     */
    fun buildRoutes(reader: GTFSReader, routePerStopSequence: Boolean = false): List<RouteData> {
        PipelineLog.info(
            if (routePerStopSequence) "Building routes, one per stop sequence"
            else "Building routes with canonical stop sequences"
        )

        // The default layout keeps 0.4.0's file order, so its output stays byte for byte the same.
        val tripSequences = reader.stopTimesData
            .groupBy { it.tripId }
            .mapValues { (_, times) ->
                (if (routePerStopSequence) times.sortedBy { it.stopSequence } else times).map { it.stopId }
            }

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

            val sequences = if (routePerStopSequence) {
                sequencesByUse(sequencesForRoute)
            } else {
                listOf(findCanonicalSequence(sequencesForRoute, "${routeId}_dir$directionId"))
            }
            for (sequence in sequences) {
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

    /** The most-run sequence; ties broken on the stops, so builds are repeatable. */
    private fun findCanonicalSequence(sequences: List<List<String>>, routeId: String): List<String> {
        if (sequences.isEmpty()) throw IllegalArgumentException("Route $routeId has no sequences")

        val counter = sequences.groupingBy { it }.eachCount()
        val maxCount = counter.values.maxOrNull() ?: 0
        val tiedSequences = counter.filterValues { it == maxCount }.keys.toList()

        return if (tiedSequences.size > 1) {
            tiedSequences.minByOrNull { it.joinToString(",") } ?: tiedSequences.first()
        } else {
            tiedSequences.first()
        }
    }
}
