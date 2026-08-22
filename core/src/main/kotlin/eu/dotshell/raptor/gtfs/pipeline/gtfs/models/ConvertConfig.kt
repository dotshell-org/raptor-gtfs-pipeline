package eu.dotshell.raptor.gtfs.pipeline.gtfs.models

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * The knobs of one conversion. Paths are not here: they belong to the request
 * ([eu.dotshell.raptor.gtfs.pipeline.ConvertRequest]), so a host can hold one configuration
 * and run it over many feeds.
 */
@Serializable
data class ConvertConfig(
    val format: String = "binary",
    val compression: Boolean = true,
    @SerialName("debug_json")
    val debugJson: Boolean = false,
    @SerialName("gen_transfers")
    val genTransfers: Boolean = false,
    @SerialName("allow_partial_trips")
    val allowPartialTrips: Boolean = false,
    @SerialName("speed_walk")
    val speedWalk: Double = 1.33,
    @SerialName("transfer_cutoff")
    val transferCutoff: Int = 500,
    val jobs: Int = 1,
    @SerialName("split_by_periods")
    val splitByPeriods: Boolean = false,
    @SerialName("gen_traces")
    val genTraces: Boolean = false,
    /** Reports the period plan and writes nothing. */
    @SerialName("dry_run")
    val dryRun: Boolean = false,
    @SerialName("flat_output")
    val flatOutput: Boolean = false,
    @SerialName("write_index")
    val writeIndex: Boolean = true
)
