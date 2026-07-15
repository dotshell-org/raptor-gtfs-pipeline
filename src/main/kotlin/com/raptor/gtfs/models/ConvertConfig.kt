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
