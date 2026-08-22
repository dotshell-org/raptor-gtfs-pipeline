package eu.dotshell.raptor.gtfs.pipeline.output

import eu.dotshell.raptor.gtfs.pipeline.gtfs.models.StopData
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * Guards the RST3 stops binary layout: the per-stop fare zone is written as a
 * length-prefixed string right after `lon`, an absent zone becomes an empty string,
 * and the header advertises magic "RST3" / version 3.
 */
class StopsWriterZoneTest {

    @Test
    fun writesRst3HeaderAndRoundTripsZones() {
        val zoned = StopData(
            stopIdInternal = 42,
            stopIdGtfs = "S42",
            name = "Bellecour",
            lat = 45.7578,
            lon = 4.8320,
            zone = "Zone Externe",
            routeIds = mutableListOf(7, 9),
            transfers = mutableListOf(3 to 120)
        )
        val unzoned = StopData(
            stopIdInternal = 43,
            stopIdGtfs = "S43",
            name = "Perrache",
            lat = 45.7494,
            lon = 4.8264,
            zone = null
        )

        val bytes = ByteArrayOutputStream().use { out ->
            StopsWriter(out).apply {
                writeHeader(schemaVersion = 3, stopCount = 2)
                writeStop(zoned)
                writeStop(unzoned)
            }
            out.toByteArray()
        }

        val buffer = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)

        val magic = ByteArray(4).also { buffer.get(it) }
        assertEquals("RST3", String(magic, Charsets.US_ASCII))
        assertEquals(3, buffer.short.toInt() and 0xFFFF) // schema version
        assertEquals(2, buffer.int) // stop count

        val first = readStop(buffer)
        assertEquals(42, first.id)
        assertEquals("Bellecour", first.name)
        assertEquals("Zone Externe", first.zone)
        assertEquals(listOf(7, 9), first.routeIds)
        assertEquals(listOf(3 to 120), first.transfers)

        val second = readStop(buffer)
        assertEquals(43, second.id)
        assertEquals("Perrache", second.name)
        assertEquals("", second.zone) // null zone serialized as empty string
        assertEquals(emptyList(), second.routeIds)
        assertEquals(emptyList(), second.transfers)
    }

    private data class ParsedStop(
        val id: Int,
        val name: String,
        val lat: Double,
        val lon: Double,
        val zone: String,
        val routeIds: List<Int>,
        val transfers: List<Pair<Int, Int>>
    )

    private fun readStop(buffer: ByteBuffer): ParsedStop {
        val id = buffer.int
        val name = readString(buffer)
        val lat = buffer.double
        val lon = buffer.double
        val zone = readString(buffer)
        val routeIds = (0 until buffer.int).map { buffer.int }
        val transfers = (0 until buffer.int).map { buffer.int to buffer.int }
        return ParsedStop(id, name, lat, lon, zone, routeIds, transfers)
    }

    private fun readString(buffer: ByteBuffer): String {
        val length = buffer.short.toInt() and 0xFFFF
        val bytes = ByteArray(length).also { buffer.get(it) }
        return String(bytes, Charsets.UTF_8)
    }
}
