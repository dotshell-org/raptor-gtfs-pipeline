package com.raptor.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class RouteData(
    val route_id_internal: Int,
    val route_id_gtfs: String,
    val route_name: String,
    val stop_ids: List<Int>,
    val trips: MutableList<TripData> = mutableListOf()
)
