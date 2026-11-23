"""Strict observed AWC music-channel framing and optional PCM/WAV export.

Only zero-skip mono Opus channels are decoded. Nonzero block-skip meanings and
original sample alignment remain unconfirmed. The inherited 312-frame trim is
explicit metadata; no missing packet, channel or sample is silently replaced.
"""
from __future__ import annotations

import hashlib
import struct

from . import audio, audio_pcm

PROFILE = 'observed_awc_music_zero_skip_pcm_v1'
MAX_BANK_BYTES = 256 * 1024 * 1024
MAX_NODES = 100000


class MusicUnsupportedError(ValueError):
    """Music storage or skip semantics are outside the observed WAV profile."""


def _integer(value, label, *, minimum=0, maximum=None):
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f'invalid music {label}')
    return value


def inspect_channels(bank: bytes, stream: dict, *, max_nodes: int = MAX_NODES) -> dict:
    """Validate complete observed music storage without loading a decoder.

    Every channel block, seek counter and padding span is checked before any
    channel list is returned. Seek counters are structural duration relations,
    not proof of nonzero skip semantics. Nonzero-skip channels remain visible
    with an explicit unsupported reason; their packets are not decoded here.
    """
    _integer(max_nodes, 'node limit', minimum=1, maximum=MAX_NODES)
    if len(bank) > MAX_BANK_BYTES:
        raise ValueError('music container exceeds size limit')
    music = stream.get('music')
    if not isinstance(music, dict) or music.get('error'):
        raise MusicUnsupportedError('music WAV requires a supported music descriptor')
    channels = music.get('channels')
    if not isinstance(channels, list) or not 1 <= len(channels) <= 32:
        raise ValueError('invalid music channel table')
    count = len(channels)
    blocks = _integer(music.get('blocks'), 'block count', minimum=1, maximum=131072)
    chunk = _integer(music.get('chunk_bytes'), 'chunk size', minimum=audio.BLOCK, maximum=16*1024*1024)
    if chunk % audio.BLOCK:
        raise ValueError('music chunk size is not a whole 2 KiB allocation')
    data_at = _integer(stream.get('data_offset'), 'data offset')
    data_size = _integer(stream.get('data_bytes'), 'data size', minimum=1, maximum=audio_pcm.MAX_INPUT_BYTES)
    if data_at > len(bank)-data_size or data_size % audio.BLOCK:
        raise ValueError('music data span exceeds the complete container or allocation')
    if not (blocks-1)*chunk < data_size <= blocks*chunk:
        raise ValueError('music block count does not account for the full data allocation')
    descriptor_at = _integer(stream.get('music_offset'), 'descriptor offset')
    descriptor_size = _integer(stream.get('music_size'), 'descriptor size', minimum=12)
    if descriptor_size != 12+16*count or descriptor_at > len(bank)-descriptor_size:
        raise ValueError('music descriptor table exceeds its exact bounded span')
    if max(descriptor_at, data_at) < min(descriptor_at+descriptor_size, data_at+data_size):
        raise ValueError('music descriptor overlaps its data allocation')
    if struct.unpack_from('<3I', bank, descriptor_at) != (blocks, chunk, count):
        raise ValueError('music descriptor metadata differs from source words')
    needed = 1+count+blocks*(1+count)
    if needed > max_nodes:
        raise ValueError('music channel metadata exceeds node limit')
    result = []
    for index, channel in enumerate(channels):
        if (not isinstance(channel, dict) or type(channel.get('index')) is not int
                or channel.get('index') != index):
            raise ValueError('music channels differ from descriptor order')
        raw_at = descriptor_at+12+16*index
        identifier = struct.unpack_from('<I', bank, raw_at)[0] & 0x1fffffff
        samples = struct.unpack_from('<I', bank, raw_at+4)[0]
        rate = struct.unpack_from('<H', bank, raw_at+10)[0]
        codec = bank[raw_at+12]
        if (channel.get('id') != identifier or channel.get('samples') != samples
                or channel.get('sample_rate') != rate or channel.get('codec') != codec):
            raise ValueError('music channel metadata differs from source descriptor')
        if codec != 0x0b or rate != audio_pcm.RATE:
            raise MusicUnsupportedError('music WAV requires all channels to use observed 48 kHz Opus storage')
        if not samples:
            raise MusicUnsupportedError('music WAV requires positive declared channel samples')
        result.append(dict(index=index, id=identifier, samples=samples, sample_rate=rate,
            codec=codec, spans=[], supported_wav=True))
    counters = [0]*count
    packet_total = 0
    block_views = []
    for block in range(blocks):
        start = data_at+block*chunk
        size = min(chunk, data_size-block*chunk)
        if 24*count > size:
            raise ValueError('truncated music block channel records')
        records = [struct.unpack_from('<6I', bank, start+24*i) for i in range(count)]
        if any(row[0] != 0xffffffff or row[4] or row[5] for row in records):
            raise MusicUnsupportedError('unsupported music block record profile')
        total = sum(row[1] for row in records)
        if any(not row[1] for row in records):
            raise MusicUnsupportedError('empty music channel block is not validated')
        table_end = 24*count+4*total
        header = (table_end+audio.BLOCK-1)//audio.BLOCK*audio.BLOCK
        used = header+total*audio.BLOCK
        if used > size:
            raise ValueError('music channel allocations exceed block bounds')
        if block == blocks-1 and used != size:
            raise ValueError('final music block has unaccounted allocation bytes')
        if any(bank[start+table_end:start+header]) or any(bank[start+used:start+size]):
            raise ValueError('nonzero music block header or tail padding')
        cursor, table_index = header, 0
        for index, row in enumerate(records):
            begin = start+cursor
            skip = row[2]
            if skip > counters[index]:
                raise ValueError('music seek counter would become negative')
            counters[index] -= skip
            decoded = packets_count = 0
            for sub in range(row[1]):
                seek_at = start+24*count+4*table_index
                table_index += 1
                if struct.unpack_from('<I', bank, seek_at)[0] != counters[index]:
                    raise ValueError('music seek counter differs from complete packet durations')
                sub_at = start+cursor
                packets = audio_pcm.strict_packets(bank[sub_at:sub_at+audio.BLOCK])
                cursor += audio.BLOCK
                packet_total += len(packets)
                if packet_total > audio_pcm.MAX_PACKETS:
                    raise ValueError('music packet count exceeds limit')
                durations = [audio.packet_samples(packet) for packet in packets]
                if any(not 1 <= n <= audio_pcm.MAX_PACKET_FRAMES for n in durations):
                    raise ValueError('invalid music Opus packet duration')
                frames = sum(durations)
                counters[index] += frames
                if counters[index] > 0xffffffff:
                    raise ValueError('music seek counter exceeds its stored word width')
                decoded += frames
                packets_count += len(packets)
            item = dict(block_index=block, data_offset=begin, byte_length=row[1]*audio.BLOCK,
                subblocks=row[1], raw_skip=skip, raw_record_bits='0x'+bank[start+24*index:start+24*(index+1)][::-1].hex(),
                packet_count=packets_count, packet_frames=decoded,
                interpretation='bounded channel allocation; nonzero skip semantics unconfirmed')
            result[index]['spans'].append(item)
            if skip:
                result[index].update(supported_wav=False,
                    reason='music channel has nonzero block skip; PCM skip semantics are not established')
        block_views.append(dict(index=block, data_offset=start, byte_length=size,
            header_byte_length=header, subblocks=total, used_byte_length=used,
            padding_byte_length=size-used))
    return dict(profile=PROFILE, channels=result, blocks=block_views,
        source_data_sha256=hashlib.sha256(bank[data_at:data_at+data_size]).hexdigest(),
        summary=dict(nodes=needed, channels=count, blocks=blocks, packets=packet_total,
            supported_channels=sum(channel['supported_wav'] for channel in result)),
        interpretation='strict observed storage; skip meanings and original sample alignment unconfirmed')


def extract_wav(bank: bytes, stream: dict, channel_index: int = 0, *, library_path=None,
                pre_skip: int = audio.PRE_SKIP, max_pcm_bytes: int = audio_pcm.MAX_PCM_BYTES):
    """Decode one zero-skip music channel to WAV and explicit trim metadata.

    Declared mono frames and an assumed inherited pre-skip select the output;
    this does not recover original music alignment. Other channels and every
    allocation are validated, but only the selected channel is decoded.
    """
    view = inspect_channels(bank, stream)
    _integer(channel_index, 'channel index', maximum=len(view['channels'])-1)
    channel = view['channels'][channel_index]
    if not channel['supported_wav']:
        raise MusicUnsupportedError(channel['reason'])
    packets = []
    for span in channel['spans']:
        at, size = span['data_offset'], span['byte_length']
        packets.extend(audio_pcm.strict_packets(bank[at:at+size]))
    pcm, info = audio_pcm.decode_packets(packets, channels=1, frames=channel['samples'],
        pre_skip=pre_skip, library_path=library_path, max_pcm_bytes=max_pcm_bytes)
    info.update(profile=PROFILE, channel_index=channel_index, channel_id=channel['id'],
        declared_samples=channel['samples'], music_blocks=len(channel['spans']),
        source_data_sha256=view['source_data_sha256'], block_skips=[span['raw_skip'] for span in channel['spans']],
        pre_skip_assumption='312 inherited from existing Ogg policy' if pre_skip == 312 else 'explicit caller value')
    return audio_pcm.wav_bytes(pcm, channels=1), info
