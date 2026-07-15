package com.raptor.output

import com.raptor.gtfs.models.*
import com.raptor.transform.TimeCompressor
import java.io.OutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

open class BinaryWriter(private val stream: OutputStream) {
    var offset = 0L

    fun writeBytes(data: ByteArray) {
        stream.write(data)
        offset += data.size
    }

    private fun writeBuffer(size: Int, block: (ByteBuffer) -> Unit) {
        val buffer = ByteBuffer.allocate(size).order(ByteOrder.LITTLE_ENDIAN)
        block(buffer)
        writeBytes(buffer.array())
    }

    fun writeUint16(value: Int) = writeBuffer(2) { it.putShort(value.toShort()) }
    fun writeUint32(value: Int) = writeBuffer(4) { it.putInt(value) }
    fun writeUint64(value: Long) = writeBuffer(8) { it.putLong(value) }
    fun writeInt32(value: Int) = writeBuffer(4) { it.putInt(value) }
    fun writeFloat64(value: Double) = writeBuffer(8) { it.putDouble(value) }

    fun writeString(value: String) {
        val encoded = value.toByteArray(Charsets.UTF_8)
        writeUint16(encoded.size)
        writeBytes(encoded)
    }
}

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

class StopsWriter(stream: OutputStream) : BinaryWriter(stream) {
    private val magic = "RST2".toByteArray(Charsets.US_ASCII)

    fun writeHeader(schemaVersion: Int, stopCount: Int) {
        writeBytes(magic)
        writeUint16(schemaVersion)
        writeUint32(stopCount)
    }

    fun writeStop(stop: StopData): Long {
        val stopOffset = offset

        writeUint32(stop.stop_id_internal)
        writeString(stop.name)
        writeFloat64(stop.lat)
        writeFloat64(stop.lon)

        writeUint32(stop.route_ids.size)
        for (routeId in stop.route_ids) writeUint32(routeId)

        writeUint32(stop.transfers.size)
        for ((targetStop, walkTime) in stop.transfers) {
            writeUint32(targetStop)
            writeInt32(walkTime)
        }

        return stopOffset
    }
}

class IndexWriter(stream: OutputStream) : BinaryWriter(stream) {
    private val magic = "RIDX".toByteArray(Charsets.US_ASCII)

    fun writeHeader(schemaVersion: Int) {
        writeBytes(magic)
        writeUint16(schemaVersion)
    }

    fun writeIndex(index: NetworkIndex) {
        writeUint32(index.stop_to_routes.size)
        for ((stopId, routeIds) in index.stop_to_routes.toSortedMap()) {
            writeUint32(stopId)
            writeUint32(routeIds.size)
            for (routeId in routeIds) writeUint32(routeId)
        }

        writeUint32(index.route_offsets.size)
        for ((routeId, routeOffset) in index.route_offsets.toSortedMap()) {
            writeUint32(routeId)
            writeUint64(routeOffset.toLong())
        }

        writeUint32(index.stop_offsets.size)
        for ((stopId, stopOffset) in index.stop_offsets.toSortedMap()) {
            writeUint32(stopId)
            writeUint64(stopOffset.toLong())
        }
    }
}

class LinesWriter(stream: OutputStream) : BinaryWriter(stream) {
    private val magic = "RLN2".toByteArray(Charsets.US_ASCII)

    fun writeHeader(schemaVersion: Int, coordScale: Int, lineCount: Int) {
        writeBytes(magic)
        writeUint16(schemaVersion)
        writeUint32(coordScale)
        writeUint32(lineCount)
    }

    fun writeLine(line: LineData, coordScale: Int): Long {
        val lineOffset = offset

        writeUint32(line.line_id_internal)
        writeString(line.name)
        writeString(line.color)
        writeString(line.text_color)
        writeUint16(line.transport_type)
        writeUint16(line.paths.size)

        for (path in line.paths) {
            writeUint16(path.direction_id)
            writeUint32(path.points.size)

            val xs = path.points.map { Math.round(it.first * coordScale).toInt() }
            val ys = path.points.map { Math.round(it.second * coordScale).toInt() }

            for (value in TimeCompressor.encodeTimes(xs)) writeInt32(value)
            for (value in TimeCompressor.encodeTimes(ys)) writeInt32(value)
        }

        return lineOffset
    }
}
