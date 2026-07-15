package com.raptor.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class ConvertConfig(
    val input_path: String,
    val output_path: String,
    val format: String = "binary",
    val compression: Boolean = true,
    val debug_json: Boolean = false,
    val gen_transfers: Boolean = false,
    val allow_partial_trips: Boolean = false,
    val speed_walk: Double = 1.33,
    val transfer_cutoff: Int = 500,
    val jobs: Int = 1,
    val split_by_periods: Boolean = false,
    val gen_traces: Boolean = false,
    val dry_run: Boolean = false,
    val flat_output: Boolean = false,
    val write_index: Boolean = true,
    val pelo: Boolean = false
)

@Serializable
data class TripData(
    val trip_id_internal: Int,
    val trip_id_gtfs: String,
    val arrival_times: List<Float>,
    val is_partial: Boolean = false
)

@Serializable
data class RouteData(
    val route_id_internal: Int,
    val route_id_gtfs: String,
    val route_name: String,
    val stop_ids: List<Int>,
    val trips: MutableList<TripData> = mutableListOf()
)

@Serializable
data class StopData(
    val stop_id_internal: Int,
    val stop_id_gtfs: String,
    val name: String,
    val lat: Double,
    val lon: Double,
    val route_ids: MutableList<Int> = mutableListOf(),
    // Pair of (target_stop_id, walk_time)
    val transfers: MutableList<Pair<Int, Int>> = mutableListOf()
)

@Serializable
data class LinePath(
    val direction_id: Int,
    val points: MutableList<Pair<Double, Double>> = mutableListOf()
)

@Serializable
data class LineData(
    val line_id_internal: Int,
    val name: String,
    val transport_type: Int,
    val color: String = "",
    val text_color: String = "",
    val paths: MutableList<LinePath> = mutableListOf()
)

@Serializable
data class Manifest(
    val schema_version: Int,
    val tool_version: String,
    val created_at_iso: String,
    val inputs: Map<String, String>, // Changed from Any since JSON serializes map of strings mostly
    val outputs: Map<String, String>,
    val stats: Map<String, Int>,
    val build: Map<String, String>
)

@Serializable
data class ServicePeriod(
    val name: String,
    val service_ids: MutableList<String> = mutableListOf(),
    val description: String = ""
)

@Serializable
data class PeriodRule(
    val days: List<String> = emptyList(),
    val service_id_matches: String? = null,
    val description: String = ""
)

@Serializable
data class Profile(
    val network: String = "",
    val periods: Map<String, PeriodRule>,
    val unmatched: String = "other"
)

@Serializable
data class NetworkIndex(
    val stop_to_routes: MutableMap<Int, MutableList<Int>> = mutableMapOf(),
    val route_offsets: MutableMap<Int, Int> = mutableMapOf(),
    val stop_offsets: MutableMap<Int, Int> = mutableMapOf()
)
