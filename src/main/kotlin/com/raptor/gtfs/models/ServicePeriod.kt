package com.raptor.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class ServicePeriod(
    val name: String,
    val service_ids: MutableList<String> = mutableListOf(),
    val description: String = ""
)
