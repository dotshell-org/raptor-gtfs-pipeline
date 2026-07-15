package com.raptor.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class Transfer(
    val from_stop_id: String,
    val to_stop_id: String,
    val min_transfer_time: Int
)
