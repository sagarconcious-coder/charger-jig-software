"""Binary packet framing for the custom JIG USB tool.

Frame layout (21 bytes total):
    0-2   Header       0x2A 0x26 0x24
    3     Msg ID (mld) 1 = CAN frame, 2 = baudrate ack
    4-7   CAN ID       uint32 little-endian
    8     Payload len  usually 8
    9-16  Payload      8 raw CAN data bytes
    17-18 CRC16        little-endian, CRC-16/ARC over bytes 0-16
    19-20 Terminator   0x0D 0x0A
"""
from __future__ import annotations

from dataclasses import dataclass

HEADER = b"\x2A\x26\x24"
TERMINATOR = b"\x0D\x0A"

HEADER_LEN = 3
FRAME_LEN = 21
CRC_COVERED_LEN = 17  # bytes 0-16 inclusive

MLD_CAN_FRAME = 1
MLD_BAUDRATE_ACK = 2


def crc16_arc(data: bytes) -> int:
    """CRC-16/ARC: poly 0xA001 (reflected), init 0xFFFF, no xorout."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


@dataclass(frozen=True)
class ParsedFrame:
    mld: int
    can_id: int
    dlc: int
    payload: bytes


class FrameParseError(Exception):
    pass


def parse_frame(frame: bytes) -> ParsedFrame:
    """Parse and validate a single 21-byte frame. Raises FrameParseError on failure."""
    if len(frame) != FRAME_LEN:
        raise FrameParseError(f"expected {FRAME_LEN} bytes, got {len(frame)}")
    if frame[0:3] != HEADER:
        raise FrameParseError("bad header")
    if frame[19:21] != TERMINATOR:
        raise FrameParseError("bad terminator")

    expected_crc = int.from_bytes(frame[17:19], "little")
    actual_crc = crc16_arc(frame[0:CRC_COVERED_LEN])
    if expected_crc != actual_crc:
        raise FrameParseError(f"CRC mismatch: expected {expected_crc:04X}, got {actual_crc:04X}")

    mld = frame[3]
    can_id = int.from_bytes(frame[4:8], "little")
    dlc = frame[8]
    payload = frame[9:9 + 8][:dlc]

    return ParsedFrame(mld=mld, can_id=can_id, dlc=dlc, payload=payload)


def build_frame(mld: int, can_id: int, payload: bytes) -> bytes:
    """Build a 21-byte frame (mainly for tests / mock generation)."""
    dlc = len(payload)
    if dlc > 8:
        raise ValueError("payload too long")
    padded_payload = payload + b"\x00" * (8 - dlc)

    body = bytearray()
    body += HEADER
    body += bytes([mld])
    body += can_id.to_bytes(4, "little")
    body += bytes([dlc])
    body += padded_payload

    crc = crc16_arc(bytes(body))
    body += crc.to_bytes(2, "little")
    body += TERMINATOR
    return bytes(body)


class StreamFramer:
    """Resync-capable framer for a continuous byte stream.

    Feed raw bytes via feed(); returns any complete frames found so far.
    On CRC/terminator failure, resyncs by searching for the next header
    byte-by-byte rather than dropping the whole buffer.
    """

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[ParsedFrame]:
        self._buf += data
        frames: list[ParsedFrame] = []

        while True:
            idx = self._buf.find(HEADER)
            if idx == -1:
                # keep at most len(HEADER)-1 trailing bytes that could be a partial header
                if len(self._buf) > HEADER_LEN - 1:
                    del self._buf[: len(self._buf) - (HEADER_LEN - 1)]
                break

            if idx > 0:
                del self._buf[:idx]

            if len(self._buf) < FRAME_LEN:
                break

            candidate = bytes(self._buf[:FRAME_LEN])
            try:
                frame = parse_frame(candidate)
                frames.append(frame)
                del self._buf[:FRAME_LEN]
            except FrameParseError:
                # not a valid frame at this position; skip past this header byte and resync
                del self._buf[:HEADER_LEN]

        return frames
