package eu.dotshell.raptor.gtfs.pipeline.gtfs.models

import kotlinx.serialization.Serializable

/**
 * A row of the optional GTFS `feed_info.txt`.
 *
 * The dates matter more than they look: `feedEndDate` is the publisher's own
 * statement of how long this feed may be trusted, and it is usually much EARLIER
 * than the last `end_date` found in `calendar.txt` (operators routinely declare
 * service patterns far beyond the window they actually commit to). Deriving
 * validity from the calendar alone would therefore be over-optimistic.
 */
@Serializable
data class FeedInfo(
    @kotlinx.serialization.SerialName("feed_publisher_name")
    val publisherName: String = "",
    @kotlinx.serialization.SerialName("feed_start_date")
    val startDate: String = "",
    @kotlinx.serialization.SerialName("feed_end_date")
    val endDate: String = "",
    @kotlinx.serialization.SerialName("feed_version")
    val version: String = ""
)
