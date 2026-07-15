package com.raptor.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class LineData(
    val line_id_internal: Int,
    val name: String,
    val transport_type: Int,
    val color: String = "",
    val text_color: String = "",
    val paths: MutableList<LinePath> = mutableListOf()
)
