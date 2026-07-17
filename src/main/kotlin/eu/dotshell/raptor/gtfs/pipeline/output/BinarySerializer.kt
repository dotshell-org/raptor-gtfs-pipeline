package eu.dotshell.raptor.gtfs.pipeline.output

import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.NetworkIndex
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.RouteData
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.StopData
import java.io.File

object BinarySerializer {
    fun writeBinaryFiles(
        outputPath: File,
        routes: List<RouteData>,
        stops: List<StopData>,
        index: NetworkIndex,
        schemaVersion: Int,
        compression: Boolean = true,
        suffix: String = "",
        writeIndex: Boolean = true
    ): Map<String, String> {
        println("Writing binary files to $outputPath")
        outputPath.mkdirs()
        val filesWritten = mutableMapOf<String, String>()

        val routesName = "routes$suffix.bin"
        val routesPath = File(outputPath, routesName)
        routesPath.outputStream().use { f ->
            val writer = RoutesWriter(f)
            writer.writeHeader(schemaVersion, routes.size)
            for (route in routes) {
                val routeOffset = writer.writeRoute(route, compression)
                index.routeOffsets[route.routeIdInternal] = routeOffset.toInt()
            }
        }
        filesWritten[routesName] = routesPath.absolutePath

        val stopsName = "stops$suffix.bin"
        val stopsPath = File(outputPath, stopsName)
        stopsPath.outputStream().use { f ->
            val writer = StopsWriter(f)
            writer.writeHeader(schemaVersion, stops.size)
            for (stop in stops) {
                val stopOffset = writer.writeStop(stop)
                index.stopOffsets[stop.stopIdInternal] = stopOffset.toInt()
            }
        }
        filesWritten[stopsName] = stopsPath.absolutePath

        if (writeIndex) {
            val indexName = "index$suffix.bin"
            val indexPath = File(outputPath, indexName)
            indexPath.outputStream().use { f ->
                val writer = IndexWriter(f)
                writer.writeHeader(schemaVersion)
                writer.writeIndex(index)
            }
            filesWritten[indexName] = indexPath.absolutePath
        }

        return filesWritten
    }
}
