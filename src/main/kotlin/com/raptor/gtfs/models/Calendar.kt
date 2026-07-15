package com.raptor.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class Calendar(
    val service_id: String,
    val monday: Boolean,
    val tuesday: Boolean,
    val wednesday: Boolean,
    val thursday: Boolean,
    val friday: Boolean,
    val saturday: Boolean,
    val sunday: Boolean,
    val start_date: String,
    val end_date: String
)
