package com.raptor.gtfs

import com.github.doyaaaaaken.kotlincsv.dsl.csvReader
import com.raptor.gtfs.models.*
import java.io.File

data class InternalStopTime(
    val trip_id: String,
    val stop_id: String,
    val arrival_time: Int,
    val departure_time: Int,
    val stop_sequence: Int,
    val trip_id_internal: Int,
    val stop_id_internal: Int
)
