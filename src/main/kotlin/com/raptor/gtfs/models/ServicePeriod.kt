package com.raptor.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class ServicePeriod(
    val name: String,
    val serviceIds: MutableList<String> = mutableListOf(),
    val description: String = ""
)
