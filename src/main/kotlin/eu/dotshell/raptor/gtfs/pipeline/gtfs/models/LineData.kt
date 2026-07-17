package eu.dotshell.raptor.gtfs.pipeline.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class LineData(
    @kotlinx.serialization.SerialName("line_id_internal")
    val lineIdInternal: Int,
    val name: String,
    @kotlinx.serialization.SerialName("transport_type")
    val transportType: Int,
    val color: String = "",
    @kotlinx.serialization.SerialName("text_color")
    val textColor: String = "",
    val paths: MutableList<LinePath> = mutableListOf()
)
