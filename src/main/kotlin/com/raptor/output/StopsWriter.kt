package com.raptor.output

import com.raptor.gtfs.models.*
import java.io.OutputStream

class StopsWriter(stream: OutputStream) : BinaryWriter(stream) {
    private val magic = "RST2".toByteArray(Charsets.US_ASCII)

    fun writeHeader(schemaVersion: Int, stopCount: Int) {
        writeBytes(magic)
        writeUint16(schemaVersion)
        writeUint32(stopCount)
    }

    fun writeStop(stop: StopData): Long {
        val stopOffset = offset

        writeUint32(stop.stopIdInternal)
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
