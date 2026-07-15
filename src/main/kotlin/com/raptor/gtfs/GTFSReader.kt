package com.raptor.gtfs

import com.github.doyaaaaaken.kotlincsv.dsl.csvReader
import com.raptor.gtfs.models.*
import java.io.File

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

        private fun readCsv(name: String, required: Boolean = true, action: (Map<String, String>) -> Unit) {
        val file = getFile(name)
        if (file == null) {
            if (required) throw RuntimeException("Required file not found: $name")
            return
        }
        com.github.doyaaaaaken.kotlincsv.dsl.csvReader().open(file) {
            readAllWithHeaderAsSequence().forEach { action(it) }
        }
    }
    fun readAgencies() {
        var found = false
        readCsv("agencies.txt", required = false) { row ->
            found = true
            agencies.add(Agency(
                agencyId = row["agency_id"] ?: "",
                agencyName = row["agency_name"] ?: "",
                agencyTimezone = row["agency_timezone"] ?: ""
            ))
        }
        if (!found) {
            readCsv("agency.txt", required = false) { row ->
                agencies.add(Agency(
                    agencyId = row["agency_id"] ?: "",
                    agencyName = row["agency_name"] ?: "",
                    agencyTimezone = row["agency_timezone"] ?: ""
                ))
            }
        }
    }

    fun readStops() {
                var i = 0


        readCsv("stops.txt") { row ->

            val stopId = row["stop_id"] ?: return@readCsv
            val lat = row["stop_lat"]?.trim()?.toDoubleOrNull()
            val lon = row["stop_lon"]?.trim()?.toDoubleOrNull()
            if (lat == null || lon == null) return@readCsv

            stopIdMap[stopId] = i
            internalToStop[i] = stopId
            stops.add(Stop(
                stopId = stopId,
                name = row["stop_name"] ?: "",
                lat = lat,
                lon = lon
            ))
            i++
        }    }

    fun readRoutes() {
                var i = 0


        readCsv("routes.txt") { row ->

            val routeId = row["route_id"] ?: return@readCsv
            val routeType = row["route_type"]?.trim()?.toIntOrNull() ?: 3

            routeIdMap[routeId] = i
            internalToRoute[i] = routeId
            routes.add(Route(
                routeId = routeId,
                routeShortName = row["route_short_name"] ?: "",
                routeLongName = row["route_long_name"] ?: "",
                routeType = routeType,
                routeColor = row["route_color"] ?: "",
                routeTextColor = row["route_text_color"] ?: ""
            ))
            i++
        }    }

    fun readCalendar() {
        readCsv("calendar.txt", required = false) { row ->

            calendar.add(Calendar(
                serviceId = row["service_id"] ?: return@readCsv,
                monday = row["monday"] == "1",
                tuesday = row["tuesday"] == "1",
                wednesday = row["wednesday"] == "1",
                thursday = row["thursday"] == "1",
                friday = row["friday"] == "1",
                saturday = row["saturday"] == "1",
                sunday = row["sunday"] == "1",
                startDate = row["start_date"] ?: "",
                endDate = row["end_date"] ?: ""
            ))
        }    }

    fun readCalendarDates() {
        readCsv("calendar_dates.txt", required = false) { row ->

            val exceptionType = row["exception_type"]?.trim()?.toIntOrNull() ?: return@readCsv
            calendarDates.add(CalendarDate(
                serviceId = row["service_id"] ?: return@readCsv,
                date = row["date"] ?: "",
                exceptionType = exceptionType
            ))
        }    }

    fun readTrips() {
                var i = 0


        readCsv("trips.txt") { row ->

            val tripId = row["trip_id"] ?: return@readCsv
            val routeId = row["route_id"] ?: return@readCsv
            val serviceId = row["service_id"] ?: return@readCsv
            val directionId = row["direction_id"]?.trim()?.toIntOrNull() ?: 0
            val shapeId = row["shape_id"] ?: ""

            tripIdMap[tripId] = i
            internalToTrip[i] = tripId
            trips.add(Trip(tripId, routeId, serviceId, directionId))
            tripsData.add(InternalTrip(tripId, routeId, serviceId, directionId, shapeId, i))
            i++
        }    }

    fun readStopTimes() {
        val parsed = mutableListOf<InternalStopTime>()
        readCsv("stop_times.txt") { row ->
            val tripId = row["trip_id"] ?: return@readCsv
            val stopId = row["stop_id"] ?: return@readCsv
            val stopSeq = row["stop_sequence"]?.trim()?.toIntOrNull() ?: return@readCsv
            
            val arrTime = parseTime(row["arrival_time"])
            val depTime = parseTime(row["departure_time"]) ?: arrTime
            if (arrTime == null || depTime == null) return@readCsv

            val stopIdInternal = stopIdMap[stopId]
            val tripIdInternal = tripIdMap[tripId]
            if (stopIdInternal == null || tripIdInternal == null) return@readCsv

            parsed.add(InternalStopTime(
                tripId = tripId,
                stopId = stopId,
                arrivalTime = arrTime,
                departureTime = depTime,
                stopSequence = stopSeq,
                tripIdInternal = tripIdInternal,
                stopIdInternal = stopIdInternal
            ))
        }
        
        // Sorting by tripId and stopSequence
        parsed.sortWith(compareBy({ it.tripId }, { it.stopSequence }))
        stopTimesData = parsed
    }

    fun readTransfers() {
        readCsv("transfers.txt", required = false) { row ->

            transfers.add(Transfer(
                fromStopId = row["from_stop_id"] ?: return@readCsv,
                toStopId = row["to_stop_id"] ?: return@readCsv,
                minTransferTime = row["min_transfer_time"]?.trim()?.toIntOrNull() ?: 0
            ))
        }    }

    fun readShapes() {
        var hasRows = false
        val tempPoints = mutableListOf<Triple<String, Int, Pair<Double, Double>>>()
        readCsv("shapes.txt", required = false) { row ->
            hasRows = true
            val shapeId = row["shape_id"] ?: return@readCsv
            val lat = row["shape_pt_lat"]?.trim()?.toDoubleOrNull() ?: return@readCsv
            val lon = row["shape_pt_lon"]?.trim()?.toDoubleOrNull() ?: return@readCsv
            val seq = row["shape_pt_sequence"]?.trim()?.toIntOrNull() ?: return@readCsv
            
            tempPoints.add(Triple(shapeId, seq, Pair(lon, lat)))
        }
        
        if (!hasRows) return
        
        val grouped = tempPoints.groupBy { it.first }
        for ((shapeId, points) in grouped) {
            val sortedPoints = points.sortedBy { it.second }.map { it.third }.toMutableList()
            shapesPoints[shapeId] = sortedPoints
        }
    }
}
