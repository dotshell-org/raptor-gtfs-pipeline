package eu.dotshell.raptor.gtfs.pipeline.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class LinePath(
    @kotlinx.serialization.SerialName("direction_id")
    val directionId: Int,
    val points: MutableList<Pair<Double, Double>> = mutableListOf()
)
