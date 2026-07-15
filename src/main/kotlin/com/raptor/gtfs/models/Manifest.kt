package com.raptor.gtfs.models

import kotlinx.serialization.Serializable

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
