package com.raptor.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class TripData(
    @kotlinx.serialization.SerialName("trip_id_internal")
    val tripIdInternal: Int,
    @kotlinx.serialization.SerialName("trip_id_gtfs")
    val tripIdGtfs: String,
    @kotlinx.serialization.SerialName("arrival_times")
    val arrivalTimes: List<Float>,
    @kotlinx.serialization.SerialName("is_partial")
    val isPartial: Boolean = false
)
