package com.raptor.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class RouteData(
    @kotlinx.serialization.SerialName("route_id_internal")
    val routeIdInternal: Int,
    @kotlinx.serialization.SerialName("route_id_gtfs")
    val routeIdGtfs: String,
    val route_name: String,
    @kotlinx.serialization.SerialName("stop_ids")
    val stopIds: List<Int>,
    val trips: MutableList<TripData> = mutableListOf()
)
