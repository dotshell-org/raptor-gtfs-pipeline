package eu.dotshell.raptor.gtfs.pipeline.output

import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.*
import java.io.OutputStream

class StopsWriter(stream: OutputStream) : BinaryWriter(stream) {
    // RST3 (v3) adds a per-stop fare zone string after the lon field. The rest of the
    // record is byte-identical to RST2 so downstream readers keep the same layout.
    private val magic = "RST3".toByteArray(Charsets.US_ASCII)

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
        writeString(stop.zone ?: "")

        writeUint32(stop.routeIds.size)
        for (routeId in stop.routeIds) writeUint32(routeId)

        writeUint32(stop.transfers.size)
        for ((targetStop, walkTime) in stop.transfers) {
            writeUint32(targetStop)
            writeInt32(walkTime)
        }

        return stopOffset
    }
}
