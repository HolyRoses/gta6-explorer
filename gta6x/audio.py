"""Opus packet extraction and lossless Ogg remuxing for AWC streams.

AWC audio streams in this package are Opus at 48 kHz, stored as
``[u16 length][packet]`` records packed into 2 KiB blocks. A record never
crosses a block; a zero length or the end of the block moves to the next one.

This module extracts those packets and wraps them in a standard Ogg Opus
container (OpusHead, OpusTags, one packet per page, correct granule positions
and CRCs). Nothing is decoded or re-encoded: the result is the original Opus
bitstream in a playable container.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

BLOCK = 0x800
PRE_SKIP = 312            # Opus default encoder delay, in 48 kHz samples
RATE = 48000
SERIAL = 0x67746136       # "gta6"

__all__ = ["OpusStream", "packets", "packet_samples", "packet_channels",
           "ogg_opus", "extract_ogg"]

#: CRC-32 used by Ogg pages (polynomial 0x04C11DB7, no reflection).
_CRC_TABLE: list[int] = []
for _i in range(256):
    _crc = _i << 24
    for _ in range(8):
        _crc = ((_crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if _crc & 0x80000000 else (_crc << 1) & 0xFFFFFFFF
    _CRC_TABLE.append(_crc)


def _crc(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ _CRC_TABLE[((crc >> 24) & 0xFF) ^ byte]
    return crc


def packets(data: bytes) -> list[bytes]:
    """Opus packets from a stream's raw data (2 KiB block layout)."""
    out: list[bytes] = []
    for offset in range(0, len(data), BLOCK):
        block = data[offset:offset + BLOCK]
        at = 0
        while at + 2 <= len(block):
            length = struct.unpack_from("<H", block, at)[0]
            if length == 0 or at + 2 + length > len(block):
                break
            out.append(block[at + 2:at + 2 + length])
            at += 2 + length
    return out


def packet_samples(packet: bytes) -> int:
    """Samples at 48 kHz carried by one Opus packet (RFC 6716 section 3.1)."""
    if not packet:
        return 0
    toc = packet[0]
    config = toc >> 3
    if config < 12:
        frame = (480, 960, 1920, 2880)[config & 3]
    elif config < 16:
        frame = (480, 960)[config & 1]
    else:
        frame = (120, 240, 480, 960)[config & 3]
    mode = toc & 3
    if mode == 0:
        frames = 1
    elif mode in (1, 2):
        frames = 2
    else:
        frames = (packet[1] & 0x3F) if len(packet) > 1 else 0
    return frame * frames


def packet_channels(packet_list: list[bytes]) -> int:
    return 2 if any(packet and packet[0] & 4 for packet in packet_list) else 1


def _page(out: bytearray, sequence: int, granule: int, flags: int,
          packet: bytes) -> None:
    lacing = []
    remaining = len(packet)
    while remaining >= 255:
        lacing.append(255)
        remaining -= 255
    lacing.append(remaining)
    start = len(out)
    out += b"OggS"
    out.append(0)                        # version
    out.append(flags)                    # header type
    out += struct.pack("<q", granule)    # granule position
    out += struct.pack("<I", SERIAL)
    out += struct.pack("<I", sequence)
    out += b"\x00\x00\x00\x00"           # CRC, filled below
    out.append(len(lacing))
    out += bytes(lacing)
    out += packet
    crc = _crc(bytes(out[start:]))
    out[start + 22:start + 26] = struct.pack("<I", crc)


def ogg_opus(packet_list: list[bytes], frames: int,
             title: str = "gta6x") -> bytes:
    """Build a complete Ogg Opus file from packets and per-channel frames."""
    if not packet_list:
        raise ValueError("no Opus packets")
    channels = packet_channels(packet_list)
    out = bytearray()
    head = bytearray(b"OpusHead")
    head.append(1)
    head.append(channels)
    head += struct.pack("<H", PRE_SKIP)
    head += struct.pack("<I", RATE)
    head += struct.pack("<h", 0)         # output gain
    head.append(0)                       # mapping family
    _page(out, 0, 0, 0x02, bytes(head))
    vendor = b"gta6x"
    comment = f"TITLE={title}".encode("utf-8")
    tags = b"OpusTags" + struct.pack("<I", len(vendor)) + vendor
    tags += struct.pack("<I", 1) + struct.pack("<I", len(comment)) + comment
    _page(out, 1, 0, 0, tags)
    granule = PRE_SKIP
    end = PRE_SKIP + frames if frames > 0 else 0
    for index, packet in enumerate(packet_list):
        granule += packet_samples(packet)
        last = index + 1 == len(packet_list)
        value = min(granule, end) if (last and end) else granule
        _page(out, 2 + index, value, 0x04 if last else 0, packet)
    return bytes(out)


def extract_ogg(bank: bytes, stream: dict, title: str = "gta6x") -> bytes:
    """Ogg Opus bytes for one AWC stream entry, or raise ValueError."""
    at = stream.get("data_offset")
    length = stream.get("data_bytes") or 0
    if at is None or length <= 0:
        raise ValueError("stream has no data chunk")
    raw = bank[at:at + length]
    packets_ = packets(raw)
    if not packets_:
        raise ValueError("no Opus packets")
    channels = stream.get("channels") or packet_channels(packets_)
    samples = stream.get("samples") or 0
    frames = samples // max(1, channels)
    return ogg_opus(packets_, frames, title=title)
