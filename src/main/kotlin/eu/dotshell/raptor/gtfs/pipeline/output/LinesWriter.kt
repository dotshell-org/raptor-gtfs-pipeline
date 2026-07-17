package eu.dotshell.raptor.gtfs.pipeline.output

import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.*
import eu.dotshell.raptor.gtfs.pipeline.transform.TimeCompressor
import java.io.OutputStream

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

        writeUint32(line.lineIdInternal)
        writeString(line.name)
        writeString(line.color)
        writeString(line.textColor)
        writeUint16(line.transportType)
        writeUint16(line.paths.size)

        for (path in line.paths) {
            writeUint16(path.directionId)
            writeUint32(path.points.size)

            val xs = path.points.map { Math.round(it.first * coordScale).toInt() }
            val ys = path.points.map { Math.round(it.second * coordScale).toInt() }

            for (value in TimeCompressor.encodeTimes(xs)) writeInt32(value)
            for (value in TimeCompressor.encodeTimes(ys)) writeInt32(value)
        }

        return lineOffset
    }
}
