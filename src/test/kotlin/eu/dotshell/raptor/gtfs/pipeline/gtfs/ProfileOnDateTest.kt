package eu.dotshell.raptor.gtfs.pipeline.gtfs

import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.PeriodDef
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.PeriodRule
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.Profile
import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * `onDate` is what separates a school term from a school holiday.
 *
 * Both are ordinary weekdays. A feed distinguishes them by withdrawing services on the holiday
 * dates through calendar_dates.txt, which the span-based rules cannot see: a service running
 * September to July looks the same either side of the break. The date rule reads the withdrawal.
 */
class ProfileOnDateTest {

    /** Two weekday services: one runs all year, one is withdrawn on the holiday Thursday. */
    private fun feed(): File {
        val dir = File.createTempFile("gtfs-ondate", "").apply { delete(); mkdirs(); deleteOnExit() }
        dir.resolve("agency.txt").writeText(
            "agency_id,agency_name,agency_url,agency_timezone\nA,Agency,https://example.org,Europe/Paris\n"
        )
        dir.resolve("stops.txt").writeText("stop_id,stop_name,stop_lat,stop_lon\ns1,One,45.0,4.0\n")
        dir.resolve("routes.txt").writeText(
            "route_id,route_short_name,route_long_name,route_type\nR,1,Line,3\n"
        )
        dir.resolve("calendar.txt").writeText(
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n" +
                "allyear,1,1,1,1,1,0,0,20260901,20270702\n" +
                "schoolonly,1,1,1,1,1,0,0,20260901,20270702\n"
        )
        // The school service is withdrawn during the Toussaint break; the year-round one is not.
        dir.resolve("calendar_dates.txt").writeText(
            "service_id,date,exception_type\nschoolonly,20261029,2\n"
        )
        dir.resolve("trips.txt").writeText(
            "route_id,service_id,trip_id,direction_id\nR,allyear,t1,0\nR,schoolonly,t2,0\n"
        )
        dir.resolve("stop_times.txt").writeText(
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n" +
                "t1,08:00:00,08:00:00,s1,1\nt2,08:30:00,08:30:00,s1,1\n"
        )
        return dir
    }

    private fun periodsOf(term: String, holiday: String): Map<String, List<String>> {
        val reader = GTFSReader(feed().absolutePath)
        reader.readAll()
        val profile = Profile(
            network = "test",
            periods = mapOf(
                "school_on_weekdays" to PeriodDef(rules = listOf(PeriodRule(onDate = term))),
                "school_off_weekdays" to PeriodDef(rules = listOf(PeriodRule(onDate = holiday)))
            )
        )
        return ProfileAnalyzer.build(profile, reader).associate { it.name to it.serviceIds.sorted() }
    }

    @Test
    fun aWithdrawnServiceIsAbsentFromTheHolidayPeriod() {
        val periods = periodsOf(term = "2026-11-05", holiday = "2026-10-29")

        assertEquals(listOf("allyear", "schoolonly"), periods["school_on_weekdays"], "term Thursday")
        assertEquals(listOf("allyear"), periods["school_off_weekdays"], "holiday Thursday")
    }

    @Test
    fun bothSpellingsOfADateAreAccepted() {
        assertEquals(
            periodsOf(term = "2026-11-05", holiday = "2026-10-29"),
            periodsOf(term = "20261105", holiday = "20261029")
        )
    }

    @Test
    fun aDayTheServiceDoesNotRunOnExcludesIt() {
        // 2026-11-07 is a Saturday; neither weekday service runs.
        val periods = periodsOf(term = "2026-11-07", holiday = "2026-10-29")
        assertEquals(null, periods["school_on_weekdays"], "no service, so no period")
    }
}
