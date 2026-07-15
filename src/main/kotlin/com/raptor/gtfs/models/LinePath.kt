package com.raptor.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class LinePath(
    val direction_id: Int,
    val points: MutableList<Pair<Double, Double>> = mutableListOf()
)
