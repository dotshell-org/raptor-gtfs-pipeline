package com.raptor.optimization

import com.raptor.gtfs.models.NetworkIndex
import com.raptor.gtfs.models.RouteData
import com.raptor.gtfs.models.StopData

object NetworkIndexBuilder {
    fun buildNetworkIndex(routes: List<RouteData>, stops: List<StopData>): NetworkIndex {
        println("Building network index")
        
        val index = NetworkIndex()
        for (stop in stops) {
            if (stop.route_ids.isNotEmpty()) {
                index.stop_to_routes[stop.stop_id_internal] = stop.route_ids.sorted().toMutableList()
            }
        }
        
        println("Built index with ${index.stop_to_routes.size} stop-to-route mappings")
        return index
    }
}

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
