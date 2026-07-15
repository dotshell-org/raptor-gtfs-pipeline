package com.raptor.gtfs.models

import kotlinx.serialization.Serializable

@Serializable
data class Agency(
    val agency_id: String,
    val agency_name: String,
    val agency_timezone: String
)

@Serializable
data class Route(
    val route_id: String,
    val route_short_name: String,
    val route_long_name: String,
    val route_type: Int,
    val route_color: String = "",
    val route_text_color: String = ""
)

@Serializable
data class Stop(
    val stop_id: String,
    val name: String,
    val lat: Double,
    val lon: Double
)

@Serializable
data class StopTime(
    val trip_id: String,
    val stop_id: String,
    val arrival_time: Int,
    val departure_time: Int,
    val stop_sequence: Int
)

@Serializable
data class Trip(
    val trip_id: String,
    val route_id: String,
    val service_id: String,
    val direction_id: Int = 0
)

@Serializable
data class Calendar(
    val service_id: String,
    val monday: Boolean,
    val tuesday: Boolean,
    val wednesday: Boolean,
    val thursday: Boolean,
    val friday: Boolean,
    val saturday: Boolean,
    val sunday: Boolean,
    val start_date: String,
    val end_date: String
)

@Serializable
data class CalendarDate(
    val service_id: String,
    val date: String,
    val exception_type: Int
)

@Serializable
data class Transfer(
    val from_stop_id: String,
    val to_stop_id: String,
    val min_transfer_time: Int
)
