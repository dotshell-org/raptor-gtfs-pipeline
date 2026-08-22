package eu.dotshell.raptor.gtfs.pipeline.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class Calendar(
    @kotlinx.serialization.SerialName("service_id")
    val serviceId: String,
    val monday: Boolean,
    val tuesday: Boolean,
    val wednesday: Boolean,
    val thursday: Boolean,
    val friday: Boolean,
    val saturday: Boolean,
    val sunday: Boolean,
    @kotlinx.serialization.SerialName("start_date")
    val startDate: String,
    @kotlinx.serialization.SerialName("end_date")
    val endDate: String
)
