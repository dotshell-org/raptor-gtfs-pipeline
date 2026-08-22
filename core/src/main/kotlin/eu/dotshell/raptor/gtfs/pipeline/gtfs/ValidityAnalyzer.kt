package eu.dotshell.raptor.gtfs.pipeline.gtfs

import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.Calendar
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.CalendarDate
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.FeedInfo
import kotlinx.serialization.Serializable

/**
 * How long the produced dataset may be trusted, and where that answer came from.
 *
 * Dates are ISO `yyyy-MM-dd` (GTFS stores them as `yyyyMMdd`), so consumers can
 * compare them lexicographically as well as chronologically.
 */
@Serializable
data class DatasetValidity(
    @kotlinx.serialization.SerialName("start_date")
    val startDate: String? = null,
    @kotlinx.serialization.SerialName("end_date")
    val endDate: String? = null,
    /** `feed_info`, `calendar`, or `none` — lets a consumer weigh how firm the window is. */
    val source: String = SOURCE_NONE,
    @kotlinx.serialization.SerialName("feed_version")
    val feedVersion: String? = null,
    @kotlinx.serialization.SerialName("feed_publisher")
    val feedPublisher: String? = null
) {
    companion object {
        const val SOURCE_FEED_INFO = "feed_info"
        const val SOURCE_CALENDAR = "calendar"
        const val SOURCE_NONE = "none"
    }
}

object ValidityAnalyzer {

    /**
     * Resolves the dataset validity window.
     *
     * `feed_info.txt` wins whenever it declares an end date: it is the publisher's own
     * commitment, and it is typically MUCH earlier than the furthest `calendar.txt`
     * end date (TCL, for instance, declares service patterns more than a year out while
     * only committing to a four-month window). Falling back to the calendar maximum is
     * therefore a deliberate last resort, not an equivalent answer — hence [source],
     * so the app can say "until X" with the right amount of confidence.
     */
    fun analyze(
        feedInfo: FeedInfo?,
        calendar: List<Calendar>,
        calendarDates: List<CalendarDate>
    ): DatasetValidity {
        val feedEnd = feedInfo?.endDate?.takeIf { isGtfsDate(it) }
        if (feedEnd != null) {
            return DatasetValidity(
                startDate = feedInfo.startDate.takeIf { isGtfsDate(it) }?.let(::toIso),
                endDate = toIso(feedEnd),
                source = DatasetValidity.SOURCE_FEED_INFO,
                feedVersion = feedInfo.version.takeIf { it.isNotBlank() },
                feedPublisher = feedInfo.publisherName.takeIf { it.isNotBlank() }
            )
        }

        // No usable feed_info: fall back to the span actually covered by the calendars.
        // calendar_dates counts too — feeds that ship no calendar.txt express everything
        // as exceptions, and there an added date (exception_type 1) is a real service day.
        val starts = calendar.map { it.startDate }.filter(::isGtfsDate)
        val ends = calendar.map { it.endDate }.filter(::isGtfsDate)
        val addedDates = calendarDates.filter { it.exceptionType == 1 }.map { it.date }.filter(::isGtfsDate)

        val minDate = (starts + addedDates).minOrNull()
        val maxDate = (ends + addedDates).maxOrNull()
        // The END date is the payload of this whole feature, so a missing or malformed
        // START must not suppress it — only give up when neither bound is usable.
        if (minDate == null && maxDate == null) return DatasetValidity()

        return DatasetValidity(
            startDate = minDate?.let(::toIso),
            endDate = maxDate?.let(::toIso),
            source = DatasetValidity.SOURCE_CALENDAR,
            feedVersion = feedInfo?.version?.takeIf { it.isNotBlank() },
            feedPublisher = feedInfo?.publisherName?.takeIf { it.isNotBlank() }
        )
    }

    /** GTFS dates are 8 digits, `yyyyMMdd`. Anything else is unusable, not "just empty". */
    private fun isGtfsDate(value: String): Boolean =
        value.length == 8 && value.all { it.isDigit() }

    private fun toIso(gtfsDate: String): String =
        "${gtfsDate.substring(0, 4)}-${gtfsDate.substring(4, 6)}-${gtfsDate.substring(6, 8)}"
}
