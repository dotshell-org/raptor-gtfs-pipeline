package eu.dotshell.raptor.gtfs.pipeline.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class Trip(
    @kotlinx.serialization.SerialName("trip_id")
    val tripId: String,
    @kotlinx.serialization.SerialName("route_id")
    val routeId: String,
    @kotlinx.serialization.SerialName("service_id")
    val serviceId: String,
    @kotlinx.serialization.SerialName("direction_id")
    val directionId: Int = 0
)
