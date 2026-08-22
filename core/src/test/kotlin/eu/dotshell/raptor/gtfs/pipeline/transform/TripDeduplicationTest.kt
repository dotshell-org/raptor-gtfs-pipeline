package eu.dotshell.raptor.gtfs.pipeline.transform

import eu.dotshell.raptor.gtfs.pipeline.PipelineConverter
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.RouteData
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.TripData
import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * A period spans several days, and an operator commonly gives each day its own service id carrying
 * the same timetable. Unioned, the same departure lands in the route several times, and a timetable
 * listing 08:00 three times reads as a line running three times as often.
 *
 * The deduplication belongs to the period filter, not to route building: routes are built across
 * the whole feed, so collapsing there keeps one trip per timetable for the season and the survivor
 * may belong to a service this period does not include.
 */
class TripDeduplicationTest {

    private fun trip(id: String, vararg times: Float) =
        TripData(tripIdInternal = id.hashCode(), tripIdGtfs = id, arrivalTimes = times.toList(), isPartial = false)

    private fun route(vararg trips: TripData) = RouteData(
        routeIdInternal = 1,
        routeIdGtfs = "R",
        routeName = "1",
        directionId = 0,
        stopIds = listOf(10, 11),
        trips = trips.toMutableList()
    )

    @Test
    fun oneDepartureIsWrittenOnce() {
        val monday = trip("t_mon", 28800f, 29400f)
        val tuesday = trip("t_tue", 28800f, 29400f)
        val wednesday = trip("t_wed", 28800f, 29400f)
        val wednesdayExtra = trip("t_wed_extra", 32400f, 33000f)

        val filtered = PipelineConverter.filterRoutesByTrips(
            listOf(route(monday, tuesday, wednesday, wednesdayExtra)),
            setOf("t_mon", "t_tue", "t_wed", "t_wed_extra")
        )

        assertEquals(
            listOf(listOf(28800f, 29400f), listOf(32400f, 33000f)),
            filtered.single().trips.map { it.arrivalTimes },
            "the three identical 08:00 trips collapse to one; the 09:00 stays"
        )
    }

    @Test
    fun aDepartureSurvivesWhenItsFirstCopyIsOutOfThePeriod() {
        val monday = trip("t_mon", 28800f, 29400f)
        val tuesday = trip("t_tue", 28800f, 29400f)

        // Monday is not in this period: its copy must not take the departure with it.
        val filtered = PipelineConverter.filterRoutesByTrips(listOf(route(monday, tuesday)), setOf("t_tue"))

        assertEquals(listOf("t_tue"), filtered.single().trips.map { it.tripIdGtfs })
    }
}
