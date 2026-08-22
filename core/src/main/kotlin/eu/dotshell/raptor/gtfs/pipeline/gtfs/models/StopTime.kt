package eu.dotshell.raptor.gtfs.pipeline.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class StopTime(
    @kotlinx.serialization.SerialName("trip_id")
    val tripId: String,
    @kotlinx.serialization.SerialName("stop_id")
    val stopId: String,
    @kotlinx.serialization.SerialName("arrival_time")
    val arrivalTime: Int,
    @kotlinx.serialization.SerialName("departure_time")
    val departureTime: Int,
    @kotlinx.serialization.SerialName("stop_sequence")
    val stopSequence: Int
)
