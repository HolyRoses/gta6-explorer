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
           "ogg_opus", "extract_ogg", "music_channels", "extract_music_ogg"]

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


def music_channels(bank: bytes, stream: dict) -> list[dict]:
    """Per-channel subblock spans of an AWC music descriptor.

    The descriptor's channel records address 2 KiB subblocks inside each
    ``chunk_bytes`` block; each channel has its own count and start offset.
    Returns one dict per channel with ``spans`` (offset, length, skip).
    """
    music = stream.get("music")
    data_at = stream.get("data_offset")
    data_size = stream.get("data_bytes") or 0
    if not music or data_at is None or data_size <= 0:
        return []
    blocks = music.get("blocks") or 0
    chunk = music.get("chunk_bytes") or 0
    channels = music.get("channels") or []
    if not (blocks and chunk and channels):
        return []
    out = [{"index": entry["index"], "id": entry.get("id"),
            "samples": entry.get("samples") or 0,
            "channels_per_record": entry.get("channels_per_record"),
            "frames": entry.get("frames"),
            "sample_rate": entry.get("sample_rate") or 0,
            "codec": entry.get("codec"), "spans": []} for entry in channels]
    for block in range(blocks):
        at = data_at + block * chunk
        remaining = data_size - block * chunk
        block_size = min(chunk, remaining)
        if block_size < len(channels) * 24:
            break
        counts = []
        skips = []
        for channel in range(len(channels)):
            record = at + channel * 24
            counts.append(struct.unpack_from("<I", bank, record + 4)[0])
            skips.append(struct.unpack_from("<I", bank, record + 8)[0])
        total_subs = sum(counts)
        header = ((len(channels) * 24 + total_subs * 4 + 2047) // 2048) * 2048
        if header > block_size:
            continue
        before = 0
        for channel, count in enumerate(counts):
            if count and header + (before + count) * 2048 <= block_size:
                out[channel]["spans"].append(
                    (at + header + before * 2048, count * 2048, skips[channel]))
            before += count
    return out


def extract_music_ogg(bank: bytes, stream: dict, channel_index: int = 0,
                      title: str = "gta6x") -> bytes:
    """Ogg Opus for one channel of an AWC music descriptor."""
    channels = music_channels(bank, stream)
    if channel_index < 0 or channel_index >= len(channels):
        raise ValueError("music channel out of range")
    channel = channels[channel_index]
    frames = channel["samples"] or 0
    mode = channel.get('channels_per_record')
    descriptor = stream.get('music_offset')
    if mode is None and type(descriptor) is int and descriptor >= 0:
        at = descriptor+12+16*channel_index
        if at+16 <= len(bank):mode = bank[at+13]
    if mode not in (1, 2) or frames % mode:
        raise ValueError('music Ogg requires a supported integral mono/stereo descriptor')
    frames //= mode
    if mode == 2:
        from . import audio_music_pcm, audio_pcm, audio_ogg
        checked = audio_music_pcm.inspect_channels(bank, stream,
            max_input_bytes=audio_music_pcm.MAX_BANK_BYTES)['channels'][channel_index]
        if any(span['raw_skip'] for span in checked['spans']):
            raise ValueError('stereo music with nonzero block skips is not validated')
        packets_ = []
        for span in checked['spans']:
            at, size = span['data_offset'], span['byte_length']
            packets_.extend(audio_pcm.strict_packets(bank[at:at+size]))
        # Correct stereo granules without changing legacy mono export bytes.
        return audio_ogg.ogg_opus(packets_, frames, channels=mode, title=title,
            max_frames=0xffffffff//mode,max_input_bytes=256*1024*1024)[0]
    raw = b"".join(bank[at:at + length] for at, length, _skip in channel["spans"])
    packets_ = packets(raw)
    if not packets_:
        raise ValueError("no Opus packets")
    if packet_channels(packets_) != mode:
        raise ValueError('music Opus packet channels differ from descriptor')
    return ogg_opus(packets_, frames, title=title)


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
