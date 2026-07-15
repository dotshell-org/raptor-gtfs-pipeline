package com.raptor.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class StopData(
    val stop_id_internal: Int,
    val stop_id_gtfs: String,
    val name: String,
    val lat: Double,
    val lon: Double,
    val route_ids: MutableList<Int> = mutableListOf(),
    // Pair of (target_stop_id, walk_time)
    val transfers: MutableList<Pair<Int, Int>> = mutableListOf()
)
