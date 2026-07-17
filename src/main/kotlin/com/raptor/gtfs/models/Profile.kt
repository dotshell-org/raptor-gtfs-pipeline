package com.raptor.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class Profile(
    val network: String = "",
    val periods: Map<String, PeriodDef>,
    val unmatched: String = "other"
)
