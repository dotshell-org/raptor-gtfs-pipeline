package com.raptor.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class TripData(
    val trip_id_internal: Int,
    val trip_id_gtfs: String,
    val arrival_times: List<Float>,
    val is_partial: Boolean = false
)
