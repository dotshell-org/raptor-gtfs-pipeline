package eu.dotshell.raptor.gtfs.pipeline.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class ConvertConfig(
    @kotlinx.serialization.SerialName("input_path")
    val inputPath: String,
    @kotlinx.serialization.SerialName("output_path")
    val outputPath: String,
    val format: String = "binary",
    val compression: Boolean = true,
    @kotlinx.serialization.SerialName("debug_json")
    val debugJson: Boolean = false,
    @kotlinx.serialization.SerialName("gen_transfers")
    val genTransfers: Boolean = false,
    @kotlinx.serialization.SerialName("allow_partial_trips")
    val allowPartialTrips: Boolean = false,
    @kotlinx.serialization.SerialName("speed_walk")
    val speedWalk: Double = 1.33,
    @kotlinx.serialization.SerialName("transfer_cutoff")
    val transferCutoff: Int = 500,
    val jobs: Int = 1,
    @kotlinx.serialization.SerialName("split_by_periods")
    val splitByPeriods: Boolean = false,
    @kotlinx.serialization.SerialName("gen_traces")
    val genTraces: Boolean = false,
    @kotlinx.serialization.SerialName("dry_run")
    val dryRun: Boolean = false,
    @kotlinx.serialization.SerialName("flat_output")
    val flatOutput: Boolean = false,
    @kotlinx.serialization.SerialName("write_index")
    val writeIndex: Boolean = true
)
