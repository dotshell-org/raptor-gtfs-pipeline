package eu.dotshell.raptor.gtfs.pipeline.gtfs.models

import eu.dotshell.raptor.gtfs.pipeline.gtfs.DatasetValidity
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * `dataset.json`: what one conversion wrote, self-describing enough that a consumer
 * discovers the layout instead of guessing folder names.
 *
 * Deliberately part of the published API. A host that republishes datasets has to read this
 * file back to know what it is serving, and doing that with the pipeline's own type — rather
 * than a hand-rolled parser on the other side — is what keeps the two ends from drifting.
 */
@Serializable
data class DatasetIndex(
    /** Container version of routes, index and lines. A consumer that cannot parse it must not download. */
    @SerialName("schema_version")
    val schemaVersion: Int,
    /**
     * Stops carry their own container version and evolve independently of routes/index/lines.
     * BOTH are declared: a consumer able to parse one format but not the other would otherwise
     * fetch a dataset it cannot read.
     */
    @SerialName("stops_schema_version")
    val stopsSchemaVersion: Int,
    /** The pipeline build that produced this dataset. Provenance only — never a parse contract. */
    @SerialName("tool_version")
    val toolVersion: String,
    val createdAt: String,
    val input: Map<String, String>,
    /** `single`, `nested` or `flat` — how the paths below are arranged under the dataset root. */
    val layout: String,
    /** Present only when line geometry was generated: the `lines.bin` path and its coordinate scale. */
    val lines: Map<String, String>? = null,
    /** How long these timetables may be trusted, and how firm that answer is. */
    val validity: DatasetValidity,
    val periods: List<PeriodIndex>
)

/** One service period inside a [DatasetIndex]: where its binaries are, and what is in them. */
@Serializable
data class PeriodIndex(
    val name: String,
    val description: String,
    /** Logical name (`routes`, `stops`, `index`) to a path relative to the dataset root. */
    val files: Map<String, String>,
    /** Every file this period wrote, keyed by the same relative path, valued by its SHA-256. */
    val checksums: Map<String, String>,
    val stats: Map<String, Int>
)
