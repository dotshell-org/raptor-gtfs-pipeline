package eu.dotshell.raptor.gtfs.pipeline.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class Stop(
    @kotlinx.serialization.SerialName("stop_id")
    val stopId: String,
    val name: String,
    val lat: Double,
    val lon: Double,
    @kotlinx.serialization.SerialName("zone_id")
    val zoneId: String? = null
)
