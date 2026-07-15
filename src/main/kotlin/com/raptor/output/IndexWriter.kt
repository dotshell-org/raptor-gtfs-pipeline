package com.raptor.output

import com.raptor.gtfs.models.*
import com.raptor.transform.TimeCompressor
import java.io.OutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

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
