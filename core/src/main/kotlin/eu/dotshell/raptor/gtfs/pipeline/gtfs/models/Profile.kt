package eu.dotshell.raptor.gtfs.pipeline.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class ProfileOptions(
    @kotlinx.serialization.SerialName("flat_output")
    val flatOutput: Boolean = false,
    @kotlinx.serialization.SerialName("write_index")
    val writeIndex: Boolean = true,
    /**
     * One route per stop sequence instead of per direction, so no trip is dropped. Only for a city
     * whose installed apps tell directions apart from the stops: older ones read a line's routes
     * as its directions. See RouteBuilder.buildRoutes.
     */
    @kotlinx.serialization.SerialName("route_per_stop_sequence")
    val routePerStopSequence: Boolean = false
)

@Serializable
data class Profile(
    val network: String = "",
    val periods: Map<String, PeriodDef>,
    val unmatched: String = "other",
    val options: ProfileOptions = ProfileOptions()
)
