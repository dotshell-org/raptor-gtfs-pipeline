package com.raptor.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class PeriodRule(
    val days: List<String> = emptyList(),
    val serviceIdMatches: String? = null,
    val activeInMonths: List<Int>? = null,
    val notActiveInMonths: List<Int>? = null,
    val maxDurationMonths: Int? = null,
    val minDurationMonths: Int? = null
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
