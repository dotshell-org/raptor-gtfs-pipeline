package com.raptor.transform

import com.raptor.gtfs.GTFSReader
import com.raptor.gtfs.models.*
import kotlin.math.*

object TimeCompressor {
    fun encodeTimes(times: List<Int>): List<Int> {
        if (times.isEmpty()) return emptyList()
        val encoded = mutableListOf(times[0])
        for (i in 1 until times.size) {
            encoded.add(times[i] - times[i - 1])
        }
        return encoded
    }

    fun decodeTimes(encoded: List<Int>): List<Int> {
        if (encoded.isEmpty()) return emptyList()
        val decoded = mutableListOf(encoded[0])
        for (i in 1 until encoded.size) {
            decoded.add(decoded.last() + encoded[i])
        }
        return decoded
    }
}
