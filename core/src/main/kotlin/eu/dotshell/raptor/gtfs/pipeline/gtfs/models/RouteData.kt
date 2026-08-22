package eu.dotshell.raptor.gtfs.pipeline.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class RouteData(
    @kotlinx.serialization.SerialName("route_id_internal")
    val routeIdInternal: Int,
    @kotlinx.serialization.SerialName("route_id_gtfs")
    val routeIdGtfs: String,
    val routeName: String,
    /**
     * The GTFS direction this route carries.
     *
     * A RAPTOR route is one stop sequence, so each direction of a line is its own route here — and
     * a route must remember which one it is. Without it, trips can only be looked up by GTFS route
     * id, and the two directions of a line become indistinguishable to anything downstream.
     */
    @kotlinx.serialization.SerialName("direction_id")
    val directionId: Int = 0,
    @kotlinx.serialization.SerialName("stop_ids")
    val stopIds: List<Int>,
    val trips: MutableList<TripData> = mutableListOf()
)
