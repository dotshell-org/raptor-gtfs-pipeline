package eu.dotshell.raptor.gtfs.pipeline.output

import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.NetworkIndex
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.RouteData
import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.StopData
import java.io.File

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

    @Suppress("UNUSED_PARAMETER")
    fun writeProtobufFiles(outputPath: File, routes: List<RouteData>, stops: List<StopData>, index: NetworkIndex): Map<String, String> {
        println("Protobuf writer is a stub - not generating .pb files")
        writeProtobufSpec(outputPath)
        return mapOf("raptor.proto" to File(outputPath, "raptor.proto").absolutePath)
    }
}
