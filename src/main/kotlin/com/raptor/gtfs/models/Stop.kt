package com.raptor.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class Stop(
    val stop_id: String,
    val name: String,
    val lat: Double,
    val lon: Double
)
