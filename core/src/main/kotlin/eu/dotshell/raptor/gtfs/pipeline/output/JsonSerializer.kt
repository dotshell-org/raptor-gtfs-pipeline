package eu.dotshell.raptor.gtfs.pipeline.output

import eu.dotshell.raptor.gtfs.pipeline.PipelineLog
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.NetworkIndex
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.RouteData
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.StopData
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.io.File

object JsonSerializer {
    private val jsonFormat = Json { prettyPrint = true }

    fun writeJsonFiles(
        outputPath: File,
        routes: List<RouteData>,
        stops: List<StopData>,
        index: NetworkIndex,
        suffix: String = "",
        writeIndex: Boolean = true
    ): Map<String, String> {
        PipelineLog.info("Writing debug JSON files to $outputPath")
        outputPath.mkdirs()
        val filesWritten = mutableMapOf<String, String>()

        val routesName = "routes$suffix.json"
        val routesPath = File(outputPath, routesName)
        routesPath.writeText(jsonFormat.encodeToString(routes))
        filesWritten[routesName] = routesPath.absolutePath

        val stopsName = "stops$suffix.json"
        val stopsPath = File(outputPath, stopsName)
        stopsPath.writeText(jsonFormat.encodeToString(stops))
        filesWritten[stopsName] = stopsPath.absolutePath

        if (writeIndex) {
            val indexName = "index$suffix.json"
            val indexPath = File(outputPath, indexName)
            indexPath.writeText(jsonFormat.encodeToString(index))
            filesWritten[indexName] = indexPath.absolutePath
        }

        return filesWritten
    }
}
