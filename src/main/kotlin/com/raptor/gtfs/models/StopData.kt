package com.raptor.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class StopData(
    @kotlinx.serialization.SerialName("stop_id_internal")
    val stopIdInternal: Int,
    @kotlinx.serialization.SerialName("stop_id_gtfs")
    val stopIdGtfs: String,
    val name: String,
    val lat: Double,
    val lon: Double,
    val routeIds: MutableList<Int> = mutableListOf(),
    // Pair of (target_stop_id, walk_time)
    val transfers: MutableList<Pair<Int, Int>> = mutableListOf()
)
