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
                index.stopToRoutes[stop.stopIdInternal] = stop.route_ids.sorted().toMutableList()
            }
        }
        
        println("Built index with ${index.stopToRoutes.size} stop-to-route mappings")
        return index
    }
}
