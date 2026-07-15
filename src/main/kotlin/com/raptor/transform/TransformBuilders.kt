package com.raptor.transform

import com.raptor.gtfs.GTFSReader
import com.raptor.gtfs.models.*
import kotlin.math.*

object StopBuilder {
    fun buildStops(reader: GTFSReader, routes: List<RouteData>): List<StopData> {
        println("Building stop data with route references")

        val stopToRoutes = mutableMapOf<Int, MutableSet<Int>>()
        for (route in routes) {
            val routeId = route.route_id_internal
            for (stopId in route.stop_ids) {
                stopToRoutes.computeIfAbsent(stopId) { mutableSetOf() }.add(routeId)
            }
        }

        val stops = mutableListOf<StopData>()
        for (stop in reader.stops) {
            val stopIdInternal = reader.stopIdMap[stop.stop_id] ?: continue
            val routeIds = stopToRoutes[stopIdInternal]?.sorted()?.toMutableList() ?: mutableListOf()

            stops.add(StopData(
                stop_id_internal = stopIdInternal,
                stop_id_gtfs = stop.stop_id,
                name = stop.name,
                lat = stop.lat,
                lon = stop.lon,
                route_ids = routeIds,
                transfers = mutableListOf()
            ))
        }

        println("Built ${stops.size} stops")
        return stops
    }
}

object RouteBuilder {
    fun buildRoutes(reader: GTFSReader): List<RouteData> {
        println("Building routes with canonical stop sequences")

        val tripSequences = reader.stopTimesData
            .groupBy { it.trip_id }
            .mapValues { (_, times) -> times.map { it.stop_id } }

        val routeNameLookup = reader.routes.associate {
            it.route_id to it.route_short_name.ifBlank { it.route_long_name }
        }

        val tripsByRouteDir = reader.tripsData
            .groupBy { Pair(it.route_id, it.direction_id) }
            .mapValues { (_, trips) -> trips.map { it.trip_id } }

        val routes = mutableListOf<RouteData>()

        for ((key, tripIds) in tripsByRouteDir.entries.sortedBy { it.key.first + "_" + it.key.second }) {
            val (routeId, directionId) = key
            val routeIdInternal = reader.routeIdMap[routeId] ?: continue

            val sequencesForRoute = tripIds.mapNotNull { tripSequences[it] }
            if (sequencesForRoute.isEmpty()) continue

            val canonicalSeq = findCanonicalSequence(sequencesForRoute, "${routeId}_dir$directionId")
            val canonicalStopIds = canonicalSeq.mapNotNull { reader.stopIdMap[it] }

            routes.add(RouteData(
                route_id_internal = routeIdInternal,
                route_id_gtfs = routeId,
                route_name = routeNameLookup[routeId] ?: "",
                stop_ids = canonicalStopIds,
                trips = mutableListOf()
            ))
        }

        println("Built ${routes.size} routes")
        return routes
    }

    private fun findCanonicalSequence(sequences: List<List<String>>, routeId: String): List<String> {
        if (sequences.isEmpty()) throw IllegalArgumentException("Route $routeId has no sequences")

        val counter = sequences.groupingBy { it }.eachCount()
        val maxCount = counter.values.maxOrNull() ?: 0
        val tiedSequences = counter.filterValues { it == maxCount }.keys.toList()

        return if (tiedSequences.size > 1) {
            tiedSequences.minByOrNull { it.joinToString(",") } ?: tiedSequences.first()
        } else {
            tiedSequences.first()
        }
    }
}

object TripBuilder {
    fun buildAndSortTrips(reader: GTFSReader, routes: List<RouteData>, allowPartial: Boolean = false) {
        println("Building and sorting trips")

        val tripsByRoute = reader.tripsData.groupBy { it.route_id }
        val stopTimesByTripInternal = reader.stopTimesData.groupBy { it.trip_id_internal }
        var totalTrips = 0

        for (route in routes) {
            val routeTrips = tripsByRoute[route.route_id_gtfs] ?: continue
            val intToGtfs = routeTrips.associate { it.trip_id_internal to it.trip_id }

            val tripDataList = mutableListOf<Pair<Float, TripData>>()

            for (trip in routeTrips) {
                val stList = stopTimesByTripInternal[trip.trip_id_internal] ?: continue
                if (stList.isEmpty()) continue

                val arrivalMap = stList.associate { it.stop_id_internal to it.arrival_time.toFloat() }
                val arrivalTimes = route.stop_ids.map { arrivalMap[it] ?: Float.POSITIVE_INFINITY }
                val isPartial = arrivalTimes.any { it.isInfinite() }

                if (isPartial && !allowPartial) continue

                val firstTime = arrivalTimes.firstOrNull() ?: Float.POSITIVE_INFINITY
                val tripData = TripData(
                    trip_id_internal = trip.trip_id_internal,
                    trip_id_gtfs = intToGtfs[trip.trip_id_internal] ?: "",
                    arrival_times = arrivalTimes,
                    is_partial = isPartial
                )
                tripDataList.add(Pair(firstTime, tripData))
            }

            tripDataList.sortBy { it.first }
            route.trips.addAll(tripDataList.map { it.second })
            totalTrips += route.trips.size
        }

        println("Built $totalTrips trips across ${routes.size} routes")
    }
}

object TransferBuilder {
    fun buildTransfers(reader: GTFSReader, stops: List<StopData>, genTransfers: Boolean = false, speedWalk: Double = 1.33, transferCutoff: Int = 500) {
        println("Building transfers")

        val gtfsToInternal = stops.associate { it.stop_id_gtfs to it.stop_id_internal }

        for (t in reader.transfers) {
            val fromInt = gtfsToInternal[t.from_stop_id]
            val toInt = gtfsToInternal[t.to_stop_id]
            if (fromInt != null && toInt != null) {
                stops[fromInt].transfers.add(Pair(toInt, t.min_transfer_time))
            }
        }

        if (genTransfers) {
            println("Generating transfers with cutoff ${transferCutoff}m and walk speed ${speedWalk}m/s")
            generateWalkingTransfers(stops, speedWalk, transferCutoff)
        }

        // Deduplicate and sort
        for (stop in stops) {
            if (stop.transfers.isNotEmpty()) {
                val transferMap = mutableMapOf<Int, Int>()
                for ((targetId, walkTime) in stop.transfers) {
                    val existing = transferMap[targetId]
                    if (existing == null || walkTime < existing) {
                        transferMap[targetId] = walkTime
                    }
                }
                stop.transfers.clear()
                stop.transfers.addAll(transferMap.entries.map { Pair(it.key, it.value) }.sortedBy { it.first })
            }
        }

        val totalTransfers = stops.sumOf { it.transfers.size }
        println("Built $totalTransfers transfers")
    }

    private fun generateWalkingTransfers(stops: List<StopData>, speedWalk: Double, cutoff: Int) {
        val n = stops.size
        if (n == 0) return

        val lats = FloatArray(n)
        val lons = FloatArray(n)
        val ids = IntArray(n)

        for (i in 0 until n) {
            lats[i] = Math.toRadians(stops[i].lat).toFloat()
            lons[i] = Math.toRadians(stops[i].lon).toFloat()
            ids[i] = stops[i].stop_id_internal
        }

        // Kotlin is fast enough to do O(n^2) nested loops directly for typical GTFS sizes (e.g. 10k-20k stops)
        // using primitive arrays.
        for (i in 0 until n) {
            val lat1 = lats[i]
            val lon1 = lons[i]
            val cosLat1 = cos(lat1)
            
            for (j in i + 1 until n) {
                val lat2 = lats[j]
                val lon2 = lons[j]

                val dlat = lat1 - lat2
                val dlon = lon1 - lon2

                val a = sin(dlat / 2).pow(2) + cosLat1 * cos(lat2) * sin(dlon / 2).pow(2)
                val dist = (6371000.0f * 2.0f * atan2(sqrt(a), sqrt(1.0f - a)))

                if (dist <= cutoff) {
                    val walkTime = (dist / speedWalk).toInt()
                    stops[i].transfers.add(Pair(ids[j], walkTime))
                    stops[j].transfers.add(Pair(ids[i], walkTime))
                }
            }
        }
    }
}

object LineGeometryBuilder {
    fun buildLines(reader: GTFSReader): List<LineData> {
        if (reader.shapesPoints.isEmpty() || reader.tripsData.isEmpty()) {
            return emptyList()
        }

        val grouped = reader.tripsData
            .filter { it.shape_id.isNotEmpty() }
            .groupBy( { Pair(it.route_id, it.direction_id) }, { it.shape_id } )
            .mapValues { (_, ids) -> ids.distinct() }

        val shapesByRoute = mutableMapOf<String, MutableMap<Int, List<String>>>()
        for ((key, shapeIds) in grouped) {
            val (routeId, directionId) = key
            shapesByRoute.computeIfAbsent(routeId) { mutableMapOf() }[directionId] = shapeIds
        }

        val lines = mutableListOf<LineData>()
        for (route in reader.routes) {
            val perDirection = shapesByRoute[route.route_id] ?: continue
            val paths = mutableListOf<LinePath>()

            for ((directionId, shapeIds) in perDirection.toSortedMap()) {
                var bestPoints: List<Pair<Double, Double>>? = null
                for (shapeId in shapeIds) {
                    val points = reader.shapesPoints[shapeId]
                    if (points != null && (bestPoints == null || points.size > bestPoints.size)) {
                        bestPoints = points
                    }
                }
                if (bestPoints != null) {
                    paths.add(LinePath(directionId, bestPoints.toMutableList()))
                }
            }

            if (paths.isEmpty()) continue

            val name = route.route_short_name.ifBlank { route.route_long_name }.ifBlank { route.route_id }
            val routeIdInternal = reader.routeIdMap[route.route_id] ?: continue

            lines.add(LineData(
                line_id_internal = routeIdInternal,
                name = name,
                transport_type = route.route_type,
                color = route.route_color,
                text_color = route.route_text_color,
                paths = paths
            ))
        }

        println("Built geometry for ${lines.size} lines")
        return lines
    }
}

object TimeCompressor {
    fun encodeTimes(times: List<Int>): List<Int> {
        if (times.isEmpty()) return emptyList()
        val encoded = mutableListOf(times[0])
        for (i in 1 until times.size) {
            encoded.add(times[i] - times[i - 1])
        }
        return encoded
    }

    fun decodeTimes(encoded: List<Int>): List<Int> {
        if (encoded.isEmpty()) return emptyList()
        val decoded = mutableListOf(encoded[0])
        for (i in 1 until encoded.size) {
            decoded.add(decoded.last() + encoded[i])
        }
        return decoded
    }
}
