package eu.dotshell.raptor.gtfs.pipeline.transform

import eu.dotshell.raptor.gtfs.pipeline.gtfs.GTFSReader
import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * A trip belongs to one direction of its line.
 *
 * Trips used to be looked up by GTFS route id alone, so both direction-routes of a line were
 * offered every trip. Where the two directions call at the same stops — a two-stop funicular is the
 * clearest case — the return trip mapped onto the outward stop order and was written into both
 * routes: the trip counted twice, and one copy had its times running backwards, which a router
 * reads as a vehicle arriving before it left.
 */
class TripDirectionTest {

    /** A two-stop line served in both directions: one trip up, one trip down. */
    private fun funicularFeed(): File {
        val dir = createTempDirectory()
        dir.resolve("agency.txt").writeText(
            "agency_id,agency_name,agency_url,agency_timezone\nA,Agency,https://example.org,Europe/Paris\n"
        )
        dir.resolve("stops.txt").writeText(
            "stop_id,stop_name,stop_lat,stop_lon\nlow,Vieux Lyon,45.7605,4.8270\nhigh,Fourviere,45.7622,4.8225\n"
        )
        dir.resolve("routes.txt").writeText(
            "route_id,route_short_name,route_long_name,route_type\nF,F2,Funiculaire,7\n"
        )
        dir.resolve("calendar.txt").writeText(
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n" +
                "S,1,1,1,1,1,1,1,20260101,20261231\n"
        )
        dir.resolve("trips.txt").writeText(
            "route_id,service_id,trip_id,direction_id\nF,S,up,0\nF,S,down,1\n"
        )
        dir.resolve("stop_times.txt").writeText(
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n" +
                "up,08:00:00,08:00:00,low,1\n" +
                "up,08:05:00,08:05:00,high,2\n" +
                "down,08:10:00,08:10:00,high,1\n" +
                "down,08:15:00,08:15:00,low,2\n"
        )
        return dir
    }

    private fun createTempDirectory(): File {
        val dir = File.createTempFile("gtfs-direction", "")
        dir.delete()
        dir.mkdirs()
        dir.deleteOnExit()
        return dir
    }

    @Test
    fun eachTripLandsInItsOwnDirectionOnly() {
        val reader = GTFSReader(funicularFeed().absolutePath)
        reader.readAll()

        val routes = RouteBuilder.buildRoutes(reader)
        TripBuilder.buildAndSortTrips(reader, routes)

        assertEquals(2, routes.size, "one route per direction")

        val written = routes.flatMap { route -> route.trips.map { it.tripIdGtfs } }
        assertEquals(listOf("down", "up"), written.sorted(), "each trip written exactly once")

        for (route in routes) {
            assertEquals(1, route.trips.size, "direction ${route.directionId} holds its own trip")
        }
    }

    @Test
    fun timesNeverRunBackwardsAlongATrip() {
        val reader = GTFSReader(funicularFeed().absolutePath)
        reader.readAll()

        val routes = RouteBuilder.buildRoutes(reader)
        TripBuilder.buildAndSortTrips(reader, routes)

        for (route in routes) {
            for (trip in route.trips) {
                val times = trip.arrivalTimes.filter { !it.isInfinite() }
                assertTrue(
                    times.zipWithNext().all { (a, b) -> b >= a },
                    "route ${route.routeName} direction ${route.directionId}, trip ${trip.tripIdGtfs}: $times"
                )
            }
        }
    }
}
