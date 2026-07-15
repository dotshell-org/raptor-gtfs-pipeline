package com.raptor.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class CalendarDate(
    @kotlinx.serialization.SerialName("service_id")
    val serviceId: String,
    val date: String,
    @kotlinx.serialization.SerialName("exception_type")
    val exceptionType: Int
)
