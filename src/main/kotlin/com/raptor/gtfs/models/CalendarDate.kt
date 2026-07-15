package com.raptor.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class CalendarDate(
    val service_id: String,
    val date: String,
    val exception_type: Int
)
