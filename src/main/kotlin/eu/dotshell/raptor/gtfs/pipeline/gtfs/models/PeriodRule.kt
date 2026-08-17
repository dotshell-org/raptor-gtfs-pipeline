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
     * A date the service must actually run on, as YYYYMMDD or YYYY-MM-DD.
     *
     * The exact rule, and the only one that can tell a school term from a school holiday: both are
     * ordinary weekdays, distinguished in a feed by which services are withdrawn on which dates.
     * The other rules read the calendar's *span*, so they cannot see a withdrawal at all — a
     * service running September to July looks identical either side of the Toussaint break.
     *
     * Evaluating it honours calendar_dates.txt, where those withdrawals live: on the TCL feed,
     * 30 072 of its 31 109 rows are removals.
     */
    val onDate: String? = null
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
