package eu.dotshell.raptor.gtfs.pipeline.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class ProfileOptions(
    @kotlinx.serialization.SerialName("flat_output")
    val flatOutput: Boolean = false,
    @kotlinx.serialization.SerialName("write_index")
    val writeIndex: Boolean = true
)

@Serializable
data class Profile(
    val network: String = "",
    val periods: Map<String, PeriodDef>,
    val unmatched: String = "other",
    val options: ProfileOptions = ProfileOptions()
)
