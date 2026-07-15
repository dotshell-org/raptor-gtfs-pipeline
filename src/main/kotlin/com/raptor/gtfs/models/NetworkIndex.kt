package com.raptor.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class NetworkIndex(
    val stop_to_routes: MutableMap<Int, MutableList<Int>> = mutableMapOf(),
    val route_offsets: MutableMap<Int, Int> = mutableMapOf(),
    val stop_offsets: MutableMap<Int, Int> = mutableMapOf()
)
