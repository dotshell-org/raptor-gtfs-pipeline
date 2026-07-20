package eu.dotshell.raptor.gtfs.pipeline.gtfs

import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.Calendar
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.CalendarDate
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.FeedInfo
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class ValidityAnalyzerTest {

    private fun calendar(serviceId: String, start: String, end: String) = Calendar(
        serviceId = serviceId,
        monday = true, tuesday = true, wednesday = true, thursday = true,
        friday = true, saturday = false, sunday = false,
        startDate = start, endDate = end
    )

    @Test
    fun `feed_info wins over a calendar that reaches much further out`() {
        // The real TCL shape: the feed commits to four months while the calendar
        // declares service patterns more than a year ahead. Trusting the calendar
        // would tell the user the timetable is good until 2027.
        val validity = ValidityAnalyzer.analyze(
            feedInfo = FeedInfo(
                publisherName = "TCL",
                startDate = "20260717",
                endDate = "20261114",
                version = ""
            ),
            calendar = listOf(calendar("s1", "20260717", "20270831")),
            calendarDates = emptyList()
        )

        assertEquals("2026-07-17", validity.startDate)
        assertEquals("2026-11-14", validity.endDate)
        assertEquals(DatasetValidity.SOURCE_FEED_INFO, validity.source)
        assertEquals("TCL", validity.feedPublisher)
        assertNull(validity.feedVersion, "a blank feed_version must not surface as an empty string")
    }

    @Test
    fun `falls back to the calendar span when feed_info is absent`() {
        val validity = ValidityAnalyzer.analyze(
            feedInfo = null,
            calendar = listOf(
                calendar("s1", "20260901", "20261231"),
                calendar("s2", "20260715", "20261120")
            ),
            calendarDates = emptyList()
        )

        assertEquals("2026-07-15", validity.startDate)
        assertEquals("2026-12-31", validity.endDate)
        assertEquals(DatasetValidity.SOURCE_CALENDAR, validity.source)
    }

    @Test
    fun `falls back to the calendar when feed_info carries a blank end date`() {
        val validity = ValidityAnalyzer.analyze(
            feedInfo = FeedInfo(publisherName = "RTM", startDate = "", endDate = "", version = "3"),
            calendar = listOf(calendar("s1", "20260101", "20260630")),
            calendarDates = emptyList()
        )

        assertEquals("2026-06-30", validity.endDate)
        assertEquals(DatasetValidity.SOURCE_CALENDAR, validity.source)
        // feed_info was unusable for dates but still identifies the feed.
        assertEquals("3", validity.feedVersion)
        assertEquals("RTM", validity.feedPublisher)
    }

    @Test
    fun `calendar_dates alone define the span for feeds with no calendar file`() {
        val validity = ValidityAnalyzer.analyze(
            feedInfo = null,
            calendar = emptyList(),
            calendarDates = listOf(
                CalendarDate("s1", "20260210", 1),
                CalendarDate("s1", "20260405", 1),
                // A removal must not extend the window past the last day of service.
                CalendarDate("s1", "20270101", 2)
            )
        )

        assertEquals("2026-02-10", validity.startDate)
        assertEquals("2026-04-05", validity.endDate)
        assertEquals(DatasetValidity.SOURCE_CALENDAR, validity.source)
    }

    @Test
    fun `malformed dates are ignored rather than surfaced`() {
        val validity = ValidityAnalyzer.analyze(
            feedInfo = FeedInfo(endDate = "2026-11-14"), // hyphenated: not a GTFS date
            calendar = listOf(calendar("s1", "oops", "20261231")),
            calendarDates = emptyList()
        )

        assertEquals(DatasetValidity.SOURCE_CALENDAR, validity.source)
        // The end date survives on its own: it is the whole point of the window.
        assertEquals("2026-12-31", validity.endDate)
        assertNull(validity.startDate, "an unusable start must not suppress a usable end")
    }

    @Test
    fun `no calendar and no feed_info yields an empty window, not a crash`() {
        val validity = ValidityAnalyzer.analyze(null, emptyList(), emptyList())

        assertNull(validity.startDate)
        assertNull(validity.endDate)
        assertEquals(DatasetValidity.SOURCE_NONE, validity.source)
    }
}
