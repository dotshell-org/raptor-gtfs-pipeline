package com.raptor.gtfs

import com.github.doyaaaaaken.kotlincsv.dsl.csvReader
import com.raptor.gtfs.models.*
import java.io.File

data class InternalTrip(
    val trip_id: String,
    val route_id: String,
    val service_id: String,
    val direction_id: Int,
    val shape_id: String,
    val trip_id_internal: Int
)
