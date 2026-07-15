package com.raptor.output

import com.raptor.gtfs.models.*
import com.raptor.transform.TimeCompressor
import java.io.OutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

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
