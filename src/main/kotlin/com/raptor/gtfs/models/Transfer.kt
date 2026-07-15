package com.raptor.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class Transfer(
    @kotlinx.serialization.SerialName("from_stop_id")
    val fromStopId: String,
    @kotlinx.serialization.SerialName("to_stop_id")
    val toStopId: String,
    @kotlinx.serialization.SerialName("min_transfer_time")
    val minTransferTime: Int
)
