package com.raptor.transform

import com.raptor.gtfs.GTFSReader
import com.raptor.gtfs.models.*
import kotlin.math.*

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
