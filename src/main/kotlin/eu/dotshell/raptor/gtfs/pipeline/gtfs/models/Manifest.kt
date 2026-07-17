package eu.dotshell.raptor.gtfs.pipeline.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class Manifest(
    @kotlinx.serialization.SerialName("schema_version")
    val schemaVersion: Int,
    @kotlinx.serialization.SerialName("tool_version")
    val toolVersion: String,
    @kotlinx.serialization.SerialName("created_at_iso")
    val createdAtIso: String,
    val inputs: Map<String, String>, // Changed from Any since JSON serializes map of strings mostly
    val outputs: Map<String, String>,
    val stats: Map<String, Int>,
    val build: Map<String, String>
)
