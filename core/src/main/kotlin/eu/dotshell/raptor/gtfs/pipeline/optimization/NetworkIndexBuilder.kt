package eu.dotshell.raptor.gtfs.pipeline.optimization

import eu.dotshell.raptor.gtfs.pipeline.PipelineLog
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.NetworkIndex
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.RouteData
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.StopData

object NetworkIndexBuilder {
    @Suppress("UNUSED_PARAMETER")
    fun buildNetworkIndex(routes: List<RouteData>, stops: List<StopData>): NetworkIndex {
        PipelineLog.info("Building network index")
        
        val index = NetworkIndex()
        for (stop in stops) {
            if (stop.routeIds.isNotEmpty()) {
                index.stopToRoutes[stop.stopIdInternal] = stop.routeIds.sorted().toMutableList()
            }
        }
        
        PipelineLog.info("Built index with ${index.stopToRoutes.size} stop-to-route mappings")
        return index
    }
}
