package com.raptor.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class Agency(
    val agency_id: String,
    val agency_name: String,
    val agency_timezone: String
)
