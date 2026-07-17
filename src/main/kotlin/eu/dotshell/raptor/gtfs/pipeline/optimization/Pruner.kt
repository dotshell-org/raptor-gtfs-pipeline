package eu.dotshell.raptor.gtfs.pipeline.optimization

import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.RouteData

object Pruner {
    fun computePruningMetadata(routes: List<RouteData>): Map<String, Int> {
        println("Computing pruning metadata (stub)")
        
        return mapOf(
            "total_routes" to routes.size,
            "total_trips" to routes.sumOf { it.trips.size },
            "total_stops" to routes.sumOf { it.stopIds.size }
        )
    }
}
