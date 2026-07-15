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
