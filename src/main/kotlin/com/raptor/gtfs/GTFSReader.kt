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

data class InternalStopTime(
    val trip_id: String,
    val stop_id: String,
    val arrival_time: Int,
    val departure_time: Int,
    val stop_sequence: Int,
    val trip_id_internal: Int,
    val stop_id_internal: Int
)

class GTFSReader(private val gtfsPath: String) {
    private val gtfsDir = File(gtfsPath)
    init {
        require(gtfsDir.isDirectory) { "GTFS path not found or not a directory: $gtfsPath" }
    }

    val stopIdMap = mutableMapOf<String, Int>()
    val routeIdMap = mutableMapOf<String, Int>()
    val tripIdMap = mutableMapOf<String, Int>()

    val internalToStop = mutableMapOf<Int, String>()
    val internalToRoute = mutableMapOf<Int, String>()
    val internalToTrip = mutableMapOf<Int, String>()

    val stops = mutableListOf<Stop>()
    val routes = mutableListOf<Route>()
    val trips = mutableListOf<Trip>()
    val transfers = mutableListOf<Transfer>()
    val agencies = mutableListOf<Agency>()
    val calendar = mutableListOf<Calendar>()
    val calendarDates = mutableListOf<CalendarDate>()
    val shapesPoints = mutableMapOf<String, MutableList<Pair<Double, Double>>>()

    var stopTimesData = mutableListOf<InternalStopTime>()
    var tripsData = mutableListOf<InternalTrip>()
    
    private fun getFile(name: String): File? {
        val f = File(gtfsDir, name)
        return if (f.exists()) f else null
    }

    private fun parseTime(timeStr: String?): Int? {
        if (timeStr.isNullOrBlank()) return null
        val parts = timeStr.trim().split(":")
        if (parts.size < 3) return null
        val h = parts[0].toIntOrNull() ?: return null
        val m = parts[1].toIntOrNull() ?: return null
        val s = parts[2].toIntOrNull() ?: return null
        return h * 3600 + m * 60 + s
    }

    fun readAll(skipStopTimes: Boolean = false) {
        println("Reading GTFS data from $gtfsPath")
        readAgencies()
        readStops()
        readRoutes()
        readCalendar()
        readCalendarDates()
        readTrips()
        if (!skipStopTimes) {
            readStopTimes()
            readTransfers()
            readShapes()
        }
    }

    private fun readCsv(name: String, required: Boolean = true): List<Map<String, String>> {
        val file = getFile(name)
        if (file == null) {
            if (required) throw RuntimeException("Required file not found: $name")
            return emptyList()
        }
        return csvReader().readAllWithHeader(file)
    }

    fun readAgencies() {
        var rows = readCsv("agencies.txt", required = false)
        if (rows.isEmpty()) rows = readCsv("agency.txt", required = false)
        if (rows.isEmpty()) return
        
        for (row in rows) {
            agencies.add(Agency(
                agency_id = row["agency_id"] ?: "",
                agency_name = row["agency_name"] ?: "",
                agency_timezone = row["agency_timezone"] ?: ""
            ))
        }
    }

    fun readStops() {
        val rows = readCsv("stops.txt")
        var i = 0
        for (row in rows) {
            val stopId = row["stop_id"] ?: continue
            val lat = row["stop_lat"]?.trim()?.toDoubleOrNull()
            val lon = row["stop_lon"]?.trim()?.toDoubleOrNull()
            if (lat == null || lon == null) continue

            stopIdMap[stopId] = i
            internalToStop[i] = stopId
            stops.add(Stop(
                stop_id = stopId,
                name = row["stop_name"] ?: "",
                lat = lat,
                lon = lon
            ))
            i++
        }
    }

    fun readRoutes() {
        val rows = readCsv("routes.txt")
        var i = 0
        for (row in rows) {
            val routeId = row["route_id"] ?: continue
            val routeType = row["route_type"]?.trim()?.toIntOrNull() ?: 3

            routeIdMap[routeId] = i
            internalToRoute[i] = routeId
            routes.add(Route(
                route_id = routeId,
                route_short_name = row["route_short_name"] ?: "",
                route_long_name = row["route_long_name"] ?: "",
                route_type = routeType,
                route_color = row["route_color"] ?: "",
                route_text_color = row["route_text_color"] ?: ""
            ))
            i++
        }
    }

    fun readCalendar() {
        val rows = readCsv("calendar.txt", required = false)
        for (row in rows) {
            calendar.add(Calendar(
                service_id = row["service_id"] ?: continue,
                monday = row["monday"] == "1",
                tuesday = row["tuesday"] == "1",
                wednesday = row["wednesday"] == "1",
                thursday = row["thursday"] == "1",
                friday = row["friday"] == "1",
                saturday = row["saturday"] == "1",
                sunday = row["sunday"] == "1",
                start_date = row["start_date"] ?: "",
                end_date = row["end_date"] ?: ""
            ))
        }
    }

    fun readCalendarDates() {
        val rows = readCsv("calendar_dates.txt", required = false)
        for (row in rows) {
            val exceptionType = row["exception_type"]?.trim()?.toIntOrNull() ?: continue
            calendarDates.add(CalendarDate(
                service_id = row["service_id"] ?: continue,
                date = row["date"] ?: "",
                exception_type = exceptionType
            ))
        }
    }

    fun readTrips() {
        val rows = readCsv("trips.txt")
        var i = 0
        for (row in rows) {
            val tripId = row["trip_id"] ?: continue
            val routeId = row["route_id"] ?: continue
            val serviceId = row["service_id"] ?: continue
            val directionId = row["direction_id"]?.trim()?.toIntOrNull() ?: 0
            val shapeId = row["shape_id"] ?: ""

            tripIdMap[tripId] = i
            internalToTrip[i] = tripId
            trips.add(Trip(tripId, routeId, serviceId, directionId))
            tripsData.add(InternalTrip(tripId, routeId, serviceId, directionId, shapeId, i))
            i++
        }
    }

    fun readStopTimes() {
        val rows = readCsv("stop_times.txt")
        val parsed = mutableListOf<InternalStopTime>()
        for (row in rows) {
            val tripId = row["trip_id"] ?: continue
            val stopId = row["stop_id"] ?: continue
            val stopSeq = row["stop_sequence"]?.trim()?.toIntOrNull() ?: continue
            
            val arrTime = parseTime(row["arrival_time"])
            val depTime = parseTime(row["departure_time"]) ?: arrTime
            if (arrTime == null || depTime == null) continue

            val stopIdInternal = stopIdMap[stopId]
            val tripIdInternal = tripIdMap[tripId]
            if (stopIdInternal == null || tripIdInternal == null) continue

            parsed.add(InternalStopTime(
                trip_id = tripId,
                stop_id = stopId,
                arrival_time = arrTime,
                departure_time = depTime,
                stop_sequence = stopSeq,
                trip_id_internal = tripIdInternal,
                stop_id_internal = stopIdInternal
            ))
        }
        
        // Sorting by trip_id and stop_sequence
        parsed.sortWith(compareBy({ it.trip_id }, { it.stop_sequence }))
        stopTimesData = parsed
    }

    fun readTransfers() {
        val rows = readCsv("transfers.txt", required = false)
        for (row in rows) {
            transfers.add(Transfer(
                from_stop_id = row["from_stop_id"] ?: continue,
                to_stop_id = row["to_stop_id"] ?: continue,
                min_transfer_time = row["min_transfer_time"]?.trim()?.toIntOrNull() ?: 0
            ))
        }
    }

    fun readShapes() {
        val rows = readCsv("shapes.txt", required = false)
        if (rows.isEmpty()) return
        
        val tempPoints = mutableListOf<Triple<String, Int, Pair<Double, Double>>>()
        for (row in rows) {
            val shapeId = row["shape_id"] ?: continue
            val lat = row["shape_pt_lat"]?.trim()?.toDoubleOrNull() ?: continue
            val lon = row["shape_pt_lon"]?.trim()?.toDoubleOrNull() ?: continue
            val seq = row["shape_pt_sequence"]?.trim()?.toIntOrNull() ?: continue
            tempPoints.add(Triple(shapeId, seq, Pair(lon, lat)))
        }
        
        val grouped = tempPoints.groupBy { it.first }
        for ((shapeId, points) in grouped) {
            val sortedPoints = points.sortedBy { it.second }.map { it.third }.toMutableList()
            shapesPoints[shapeId] = sortedPoints
        }
    }
}
