package com.raptor.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class StopTime(
    val trip_id: String,
    val stop_id: String,
    val arrival_time: Int,
    val departure_time: Int,
    val stop_sequence: Int
)
