package eu.dotshell.raptor.gtfs.pipeline.gtfs

data class InternalTrip(
    val tripId: String,
    val routeId: String,
    val serviceId: String,
    val directionId: Int,
    val shapeId: String,
    val tripIdInternal: Int
)
