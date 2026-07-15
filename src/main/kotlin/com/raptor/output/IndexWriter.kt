package com.raptor.output

import com.raptor.gtfs.models.*
import java.io.OutputStream

class IndexWriter(stream: OutputStream) : BinaryWriter(stream) {
    private val magic = "RIDX".toByteArray(Charsets.US_ASCII)

    fun writeHeader(schemaVersion: Int) {
        writeBytes(magic)
        writeUint16(schemaVersion)
    }

    fun writeIndex(index: NetworkIndex) {
        writeUint32(index.stopToRoutes.size)
        for ((stopId, routeIds) in index.stopToRoutes.toSortedMap()) {
            writeUint32(stopId)
            writeUint32(routeIds.size)
            for (routeId in routeIds) writeUint32(routeId)
        }

        writeUint32(index.routeOffsets.size)
        for ((routeId, routeOffset) in index.routeOffsets.toSortedMap()) {
            writeUint32(routeId)
            writeUint64(routeOffset.toLong())
        }

        writeUint32(index.stopOffsets.size)
        for ((stopId, stopOffset) in index.stopOffsets.toSortedMap()) {
            writeUint32(stopId)
            writeUint64(stopOffset.toLong())
        }
    }
}
