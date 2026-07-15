package com.raptor.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class PeriodRule(
    val days: List<String> = emptyList(),
    val service_id_matches: String? = null,
    val description: String = ""
)
