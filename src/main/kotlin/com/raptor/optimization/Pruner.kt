package com.raptor.optimization

import com.raptor.gtfs.models.NetworkIndex
import com.raptor.gtfs.models.RouteData
import com.raptor.gtfs.models.StopData

object Pruner {
    fun computePruningMetadata(routes: List<RouteData>): Map<String, Int> {
        println("Computing pruning metadata (stub)")
        
        return mapOf(
            "total_routes" to routes.size,
            "total_trips" to routes.sumOf { it.trips.size },
            "total_stops" to routes.sumOf { it.stop_ids.size }
        )
    }
}
