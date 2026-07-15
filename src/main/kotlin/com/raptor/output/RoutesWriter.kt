package com.raptor.output

import com.raptor.gtfs.models.*
import com.raptor.transform.TimeCompressor
import java.io.OutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

class RoutesWriter(stream: OutputStream) : BinaryWriter(stream) {
    private val magic = "RRT2".toByteArray(Charsets.US_ASCII)

    fun writeHeader(schemaVersion: Int, routeCount: Int) {
        writeBytes(magic)
        writeUint16(schemaVersion)
        writeUint32(routeCount)
    }

    fun writeRoute(route: RouteData, compression: Boolean = true): Long {
        val routeOffset = offset

        writeUint32(route.route_id_internal)
        writeString(route.route_name)
        writeUint32(route.stop_ids.size)
        writeUint32(route.trips.size)

        for (stopId in route.stop_ids) writeUint32(stopId)

        for (trip in route.trips) writeUint32(trip.trip_id_internal)

        for (trip in route.trips) {
            val times = trip.arrival_times.filter { !it.isInfinite() }.map { it.toInt() }
            val encodedTimes = if (compression) TimeCompressor.encodeTimes(times) else times
            for (time in encodedTimes) writeInt32(time)
        }

        return routeOffset
    }
}
