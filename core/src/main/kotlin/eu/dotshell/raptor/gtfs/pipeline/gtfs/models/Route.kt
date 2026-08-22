package eu.dotshell.raptor.gtfs.pipeline.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class Route(
    @kotlinx.serialization.SerialName("route_id")
    val routeId: String,
    @kotlinx.serialization.SerialName("route_short_name")
    val routeShortName: String,
    @kotlinx.serialization.SerialName("route_long_name")
    val routeLongName: String,
    @kotlinx.serialization.SerialName("route_type")
    val routeType: Int,
    @kotlinx.serialization.SerialName("route_color")
    val routeColor: String = "",
    @kotlinx.serialization.SerialName("route_text_color")
    val routeTextColor: String = ""
)
