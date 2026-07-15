package com.raptor.output

import com.raptor.gtfs.models.LineData
import com.raptor.gtfs.models.NetworkIndex
import com.raptor.gtfs.models.RouteData
import com.raptor.gtfs.models.StopData
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
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
                index.route_offsets[route.route_id_internal] = routeOffset.toInt()
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
                index.stop_offsets[stop.stop_id_internal] = stopOffset.toInt()
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
        println("Writing debug JSON files to $outputPath")
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

object LinesSerializer {
    const val COORD_SCALE = 1_000_000

    fun writeLinesFile(outputPath: File, lines: List<LineData>, schemaVersion: Int): String {
        outputPath.mkdirs()
        val linesPath = File(outputPath, "lines.bin")

        var totalPoints = 0
        linesPath.outputStream().use { f ->
            val writer = LinesWriter(f)
            writer.writeHeader(schemaVersion, COORD_SCALE, lines.size)
            for (line in lines) {
                writer.writeLine(line, COORD_SCALE)
                totalPoints += line.paths.sumOf { it.points.size }
            }
        }

        println("Wrote $linesPath (${lines.size} lines, $totalPoints points)")
        return linesPath.absolutePath
    }
}

object ProtobufSerializer {
    const val PROTO_SPEC = """syntax = "proto3";

package raptor;

message StopData {
  uint32 stop_id_internal = 1;
  string stop_id_gtfs = 2;
  string name = 3;
  double lat = 4;
  double lon = 5;
  repeated uint32 route_ids = 6;
  repeated Transfer transfers = 7;
}

message Transfer {
  uint32 target_stop_id = 1;
  int32 walk_time = 2;
}

message TripData {
  uint32 trip_id_internal = 1;
  string trip_id_gtfs = 2;
  repeated int32 arrival_times = 3;
  bool is_partial = 4;
}

message RouteData {
  uint32 route_id_internal = 1;
  string route_id_gtfs = 2;
  repeated uint32 stop_ids = 3;
  repeated TripData trips = 4;
}

message NetworkData {
  repeated RouteData routes = 1;
  repeated StopData stops = 2;
  NetworkIndex index = 3;
}

message NetworkIndex {
  map<uint32, RouteList> stop_to_routes = 1;
  map<uint32, uint64> route_offsets = 2;
  map<uint32, uint64> stop_offsets = 3;
}

message RouteList {
  repeated uint32 route_ids = 1;
}
"""

    fun writeProtobufSpec(outputPath: File) {
        val protoPath = File(outputPath, "raptor.proto")
        protoPath.writeText(PROTO_SPEC)
        println("Wrote protobuf spec to $protoPath")
    }

    fun writeProtobufFiles(outputPath: File, routes: List<RouteData>, stops: List<StopData>, index: NetworkIndex): Map<String, String> {
        println("Protobuf writer is a stub - not generating .pb files")
        writeProtobufSpec(outputPath)
        return mapOf("raptor.proto" to File(outputPath, "raptor.proto").absolutePath)
    }
}
