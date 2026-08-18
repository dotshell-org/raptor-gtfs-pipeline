package eu.dotshell.raptor.gtfs.pipeline.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class PeriodRule(
    val days: List<String> = emptyList(),
    val serviceIdMatches: String? = null,
    val activeInMonths: List<Int>? = null,
    val notActiveInMonths: List<Int>? = null,
    val maxDurationMonths: Int? = null,
    val minDurationMonths: Int? = null,
    /**
     * A single date the service must run on, as YYYYMMDD or YYYY-MM-DD.
     *
     * Rarely what you want on its own: one date is one week of one holiday. A service running only
     * during the February break is absent from every other break's date, so a period defined by a
     * lone date silently drops it. Prefer `dateRanges`, which covers each break in full; this is
     * here for the case where a period really is one day.
     */
    val onDate: String? = null,
    /** Further single dates, considered alongside `onDate` and `dateRanges`. */
    val onDates: List<String> = emptyList(),
    /**
     * Windows of the calendar the service must run in — every school holiday of the year, or every
     * stretch of term.
     *
     * The service matches if it runs on **at least one** date inside any window, restricted to the
     * rule's `days` when it has some. This is the only rule that can separate a school term from a
     * school holiday: both are ordinary weekdays, and what distinguishes them is which services are
     * withdrawn on which dates — 30 072 of the 31 109 rows of the TCL feed's calendar_dates.txt.
     * The span-based rules read a calendar's start and end and cannot see a withdrawal at all.
     *
     * Matching on "at least one date" makes a period the union of its windows: a service running
     * only over Christmas belongs to the holiday period even though it is absent at Toussaint. That
     * is what makes the output usable on any date of the year, and it does mean the period holds
     * slightly more service than any single day of it runs.
     */
    val dateRanges: List<DateRange> = emptyList()
)

/** Inclusive window of dates, each as YYYYMMDD or YYYY-MM-DD. */
@Serializable
data class DateRange(
    val from: String,
    val to: String
)

@Serializable
data class PeriodDef(
    val description: String = "",
    val rules: List<PeriodRule> = emptyList(),
    val days: List<String> = emptyList(),
    val serviceIdMatches: String? = null
) {
    fun getEffectiveRules(): List<PeriodRule> {
        if (rules.isNotEmpty()) return rules
        if (days.isNotEmpty() || serviceIdMatches != null) {
            return listOf(PeriodRule(days = days, serviceIdMatches = serviceIdMatches))
        }
        return emptyList()
    }
}
