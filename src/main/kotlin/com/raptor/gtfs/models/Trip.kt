package com.raptor.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class Trip(
    val trip_id: String,
    val route_id: String,
    val service_id: String,
    val direction_id: Int = 0
)
