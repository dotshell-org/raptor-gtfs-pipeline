package eu.dotshell.raptor.gtfs.pipeline.transform

import eu.dotshell.raptor.gtfs.pipeline.gtfs.GTFSReader
import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * Every trip of a line reaches the output, whichever stops it calls at.
 *
 * Each direction used to have one route, and a trip not covering its whole stop sequence was dropped:
 * half of line 1 of the Mistral export, and on Sundays all of lines U, 18, 72 and 81.
 */
class TripPatternTest {

    /** One direction of a line: three all-stops trips, a short turn, and a Sunday detour by another stop. */
    private fun feed(): File {
        val dir = File.createTempFile("gtfs-pattern", "")
        dir.delete()
        dir.mkdirs()
        dir.deleteOnExit()
        dir.resolve("agency.txt").writeText(
            "agency_id,agency_name,agency_url,agency_timezone\nA,Agency,https://example.org,Europe/Paris\n"
        )
        dir.resolve("stops.txt").writeText(
            "stop_id,stop_name,stop_lat,stop_lon\n" +
                "a,Alpha,43.10,5.90\nb,Bravo,43.11,5.91\nc,Charlie,43.12,5.92\nd,Delta,43.13,5.93\n"
        )
        dir.resolve("routes.txt").writeText(
            "route_id,route_short_name,route_long_name,route_type\nL,1,Ligne 1,3\n"
        )
        dir.resolve("calendar.txt").writeText(
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n" +
                "S,1,1,1,1,1,1,1,20260101,20261231\n"
        )
        dir.resolve("trips.txt").writeText(
            "route_id,service_id,trip_id,direction_id\n" +
                "L,S,late,0\nL,S,early,0\nL,S,noon,0\nL,S,short,0\nL,S,detour,0\n"
        )
        fun times(trip: String, vararg calls: Pair<String, String>) = calls.withIndex().joinToString("") { (i, call) ->
            "$trip,${call.second},${call.second},${call.first},${i + 1}\n"
        }
        dir.resolve("stop_times.txt").writeText(
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n" +
                times("late", "a" to "18:00:00", "b" to "18:05:00", "c" to "18:10:00") +
                times("early", "a" to "08:00:00", "b" to "08:05:00", "c" to "08:10:00") +
                times("noon", "a" to "12:00:00", "b" to "12:05:00", "c" to "12:10:00") +
                times("short", "a" to "09:00:00", "b" to "09:05:00") +
                times("detour", "a" to "10:00:00", "d" to "10:05:00", "c" to "10:10:00")
        )
        return dir
    }

    private fun built(): Pair<GTFSReader, List<eu.dotshell.raptor.gtfs.pipeline.gtfs.models.RouteData>> {
        val reader = GTFSReader(feed().absolutePath)
        reader.readAll()
        val routes = RouteBuilder.buildRoutes(reader)
        TripBuilder.buildAndSortTrips(reader, routes)
        return reader to routes
    }

    @Test
    fun noTripIsLost() {
        val (_, routes) = built()
        assertEquals(
            listOf("detour", "early", "late", "noon", "short"),
            routes.flatMap { route -> route.trips.map { it.tripIdGtfs } }.sorted()
        )
    }

    @Test
    fun theMostRunSequenceComesFirst() {
        val (reader, routes) = built()
        assertEquals(3, routes.size, "one route per stop sequence")
        assertEquals(
            listOf("a", "b", "c").map { reader.stopIdMap.getValue(it) },
            routes.first().stopIds
        )
        assertEquals(listOf("early", "noon", "late"), routes.first().trips.map { it.tripIdGtfs }, "sorted by departure")
    }

    @Test
    fun aTripKeepsTheTimesOfItsOwnStops() {
        val (reader, routes) = built()
        val detour = routes.single { route -> route.trips.any { it.tripIdGtfs == "detour" } }
        assertEquals(listOf("a", "d", "c").map { reader.stopIdMap.getValue(it) }, detour.stopIds)
        assertEquals(listOf(36000f, 36300f, 36600f), detour.trips.single().arrivalTimes)
    }
}
