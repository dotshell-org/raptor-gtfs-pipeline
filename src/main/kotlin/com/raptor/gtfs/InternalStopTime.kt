package com.raptor.gtfs

data class InternalStopTime(
    val tripId: String,
    val stopId: String,
    val arrivalTime: Int,
    val departureTime: Int,
    val stopSequence: Int,
    val tripIdInternal: Int,
    val stopIdInternal: Int
)
