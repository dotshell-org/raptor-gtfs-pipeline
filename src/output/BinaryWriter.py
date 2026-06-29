import struct
from typing import BinaryIO


class BinaryWriter:
    """Base class for binary writers."""

    def __init__(self, file: BinaryIO) -> None:
        """Initialize writer with file handle."""
        self.file = file
        self.offset = 0

    def write_bytes(self, data: bytes) -> None:
        """Write raw bytes and track offset."""
        self.file.write(data)
        self.offset += len(data)

    def write_uint16(self, value: int) -> None:
        """Write uint16 in little-endian."""
        self.write_bytes(struct.pack("<H", value))

    def write_uint32(self, value: int) -> None:
        """Write uint32 in little-endian."""
        self.write_bytes(struct.pack("<I", value))

    def write_uint64(self, value: int) -> None:
        """Write uint64 in little-endian."""
        self.write_bytes(struct.pack("<Q", value))

    def write_int32(self, value: int) -> None:
        """Write int32 in little-endian."""
        self.write_bytes(struct.pack("<i", value))

    def write_float64(self, value: float) -> None:
        """Write float64 in little-endian."""
        self.write_bytes(struct.pack("<d", value))

    def write_string(self, value: str) -> None:
        """Write length-prefixed UTF-8 string."""
        encoded = value.encode("utf-8")
        self.write_uint16(len(encoded))
        self.write_bytes(encoded)
