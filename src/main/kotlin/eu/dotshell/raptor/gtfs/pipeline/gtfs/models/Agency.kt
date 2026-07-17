package eu.dotshell.raptor.gtfs.pipeline.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class Agency(
    @kotlinx.serialization.SerialName("agency_id")
    val agencyId: String,
    @kotlinx.serialization.SerialName("agency_name")
    val agencyName: String,
    @kotlinx.serialization.SerialName("agency_timezone")
    val agencyTimezone: String
)
