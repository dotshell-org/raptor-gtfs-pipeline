package com.raptor.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class Route(
    val route_id: String,
    val route_short_name: String,
    val route_long_name: String,
    val route_type: Int,
    val route_color: String = "",
    val route_text_color: String = ""
)
