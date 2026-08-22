package eu.dotshell.raptor.gtfs.pipeline.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class NetworkIndex(
    @kotlinx.serialization.SerialName("stop_to_routes")
    val stopToRoutes: MutableMap<Int, MutableList<Int>> = mutableMapOf(),
    @kotlinx.serialization.SerialName("route_offsets")
    val routeOffsets: MutableMap<Int, Int> = mutableMapOf(),
    @kotlinx.serialization.SerialName("stop_offsets")
    val stopOffsets: MutableMap<Int, Int> = mutableMapOf()
)
