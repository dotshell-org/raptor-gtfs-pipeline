package eu.dotshell.raptor.gtfs.pipeline.gtfs

import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.DateRange
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
                "schoolonly,1,1,1,1,1,0,0,20260901,20270702\n" +
                "februaryonly,1,1,1,1,1,0,0,20270215,20270226\n"
        )
        // The school service is withdrawn for the whole Toussaint break, weekday by weekday, which
        // is how a feed encodes a holiday; the year-round one keeps running.
        val breaks = listOf(
            // Toussaint
            "20261019", "20261020", "20261021", "20261022", "20261023",
            "20261026", "20261027", "20261028", "20261029", "20261030",
            // February
            "20270215", "20270216", "20270217", "20270218", "20270219",
            "20270222", "20270223", "20270224", "20270225", "20270226"
        )
        dir.resolve("calendar_dates.txt").writeText(
            "service_id,date,exception_type\n" +
                breaks.joinToString("") { "schoolonly,$it,2\n" }
        )
        dir.resolve("trips.txt").writeText(
            "route_id,service_id,trip_id,direction_id\n" +
                "R,allyear,t1,0\nR,schoolonly,t2,0\nR,februaryonly,t3,0\n"
        )
        dir.resolve("stop_times.txt").writeText(
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n" +
                "t1,08:00:00,08:00:00,s1,1\nt2,08:30:00,08:30:00,s1,1\nt3,09:00:00,09:00:00,s1,1\n"
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

    private fun periodsOfWindows(
        term: Pair<String, String>,
        holidays: List<Pair<String, String>>
    ): Map<String, List<String>> {
        val reader = GTFSReader(feed().absolutePath)
        reader.readAll()
        val profile = Profile(
            network = "test",
            periods = mapOf(
                "school_on_weekdays" to PeriodDef(
                    rules = listOf(
                        PeriodRule(
                            days = listOf("mon-fri"),
                            dateRanges = listOf(DateRange(term.first, term.second))
                        )
                    )
                ),
                "school_off_weekdays" to PeriodDef(
                    rules = listOf(
                        PeriodRule(
                            days = listOf("mon-fri"),
                            dateRanges = holidays.map { DateRange(it.first, it.second) }
                        )
                    )
                )
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

    @Test
    fun everyBreakIsCoveredWhenTheWindowsListThemAll() {
        val periods = periodsOfWindows(
            term = "2026-11-02" to "2026-12-18",
            holidays = listOf("2026-10-19" to "2026-10-30", "2027-02-15" to "2027-02-26")
        )

        assertEquals(
            listOf("allyear", "februaryonly"),
            periods["school_off_weekdays"],
            "a service running only in February belongs to the holidays, like the Toussaint ones"
        )
    }

    @Test
    fun aLoneWindowDropsTheBreaksItDoesNotCover() {
        val periods = periodsOfWindows(
            term = "2026-11-02" to "2026-12-18",
            holidays = listOf("2026-10-19" to "2026-10-30")
        )

        // Why windows are a list: Toussaint alone cannot see the February-only service.
        assertEquals(listOf("allyear"), periods["school_off_weekdays"])
    }
}
