"""Guarded packet-overlap reconstruction for observed AWC music storage.

The default retains the zero-skip profile. The opt-in profile removes only an
observed-size prefix that exactly repeats both the preceding block suffix and
the reconstructed compressed packet history. This establishes packet identity,
not the game's decoder state, original alignment, or arbitrary skip semantics.
"""
from __future__ import annotations

from . import audio, audio_music_pcm as music, audio_pcm

PROFILE = 'observed_awc_music_verified_packet_overlap_v1'
MusicUnsupportedError = music.MusicUnsupportedError
POLICIES = ('zero', 'verified-overlap')
OBSERVED_SKIP_FRAMES = frozenset((960, 1920, 3840, 4800, 5760, 6720, 7680,
    8640, 12480, 13440, 14400, 16320, 17280, 19200, 21120))
OGG_PROFILE = 'observed_awc_music_declared_packet_overlap_ogg_v1'


def _policy(value):
    if value not in POLICIES:
        raise ValueError('music skip policy must be zero or verified-overlap')


def _packets(bank, channel):
    """Return a proven sequence and bounded per-block evidence, or refuse it."""
    history, previous, evidence = [], [], []
    counter = 0
    for span in channel['spans']:
        at, size = span['data_offset'], span['byte_length']
        packets = audio_pcm.strict_packets(bank[at:at+size])
        skip, count, frames = span['raw_skip'], 0, 0
        if skip:
            if skip not in OBSERVED_SKIP_FRAMES:
                raise music.MusicUnsupportedError('block skip is outside observed overlap sizes')
            for packet in packets:
                frames += audio.packet_samples(packet)
                count += 1
                if frames >= skip:
                    break
            if frames != skip:
                raise music.MusicUnsupportedError('block skip does not end at a whole packet boundary')
            prefix = packets[:count]
            if len(previous) < count or prefix != previous[-count:]:
                raise music.MusicUnsupportedError('block prefix does not exactly repeat previous block packet suffix')
            if len(history) < count or prefix != history[-count:]:
                raise music.MusicUnsupportedError('block prefix does not exactly repeat reconstructed packet history')
        start = counter-skip
        counter = start+span['packet_frames']
        history.extend(packets[count:])
        previous = packets
        evidence.append(dict(block_index=span['block_index'], raw_skip=skip,
            source_packets=len(packets), source_frames=span['packet_frames'],
            repeated_packets=count, repeated_frames=frames,
            retained_packets=len(packets)-count,
            retained_frames=span['packet_frames']-frames,
            repeated_packet_bytes=sum(len(p) for p in packets[:count]),
            counter_start_frame=start, counter_end_frame=counter,
            verified=bool(skip)))
    return history, evidence


def inspect_channels(bank: bytes, stream: dict, *, skip_policy='zero',
                     max_nodes=music.MAX_NODES):
    """Validate the entire allocation, then prove each optional overlap.

Failure to prove a channel leaves it visible with an explicit refusal reason.
The original profile performs all seek-counter, descriptor and padding checks.
"""
    _policy(skip_policy)
    view = music.inspect_channels(bank, stream, max_nodes=max_nodes)
    if skip_policy == 'zero':
        return view
    view['profile'] = PROFILE
    view['skip_policy'] = skip_policy
    view['interpretation'] = 'exact repeated compressed packets; original alignment and game decoder state unconfirmed'
    for channel in view['channels']:
        if channel.get('channels_per_record') == 2 and any(s['raw_skip'] for s in channel['spans']):
            channel.update(supported_wav=False, reason='stereo nonzero block-skip policy is not validated')
            continue
        try:
            _, evidence = _packets(bank, channel)
        except music.MusicUnsupportedError as exc:
            channel.update(supported_wav=False, reason=str(exc))
        else:
            channel.update(supported_wav=True, packet_overlap=evidence)
            channel.pop('reason', None)
    view['summary']['supported_channels'] = sum(c['supported_wav'] for c in view['channels'])
    return view


def extract_wav(bank: bytes, stream: dict, channel_index=0, *, skip_policy='zero',
                library_path=None, pre_skip=audio.PRE_SKIP,
                max_pcm_bytes=audio_pcm.MAX_PCM_BYTES):
    """Decode a proven packet sequence using the explicit inherited trim policy."""
    _policy(skip_policy)
    if skip_policy == 'zero':
        return music.extract_wav(bank, stream, channel_index, library_path=library_path,
            pre_skip=pre_skip, max_pcm_bytes=max_pcm_bytes)
    view = inspect_channels(bank, stream, skip_policy=skip_policy)
    music._integer(channel_index, 'channel index', maximum=len(view['channels'])-1)
    channel = view['channels'][channel_index]
    if not channel['supported_wav']:
        raise music.MusicUnsupportedError(channel['reason'])
    # Preserve exact default metadata and WAV bytes for every zero-skip channel.
    if not any(span['raw_skip'] for span in channel['spans']):
        return music.extract_wav(bank, stream, channel_index, library_path=library_path,
            pre_skip=pre_skip, max_pcm_bytes=max_pcm_bytes)
    packets, evidence = _packets(bank, channel)
    pcm, info = audio_pcm.decode_packets(packets, channels=1, frames=channel['samples'],
        pre_skip=pre_skip, library_path=library_path, max_pcm_bytes=max_pcm_bytes)
    info.update(profile=PROFILE, skip_policy=skip_policy, channel_index=channel_index,
        channel_id=channel['id'], declared_samples=channel['samples'],
        music_blocks=len(channel['spans']), source_data_sha256=view['source_data_sha256'],
        block_skips=[span['raw_skip'] for span in channel['spans']], packet_overlap=evidence,
        removed_repeated_packets=sum(e['repeated_packets'] for e in evidence),
        removed_repeated_frames=sum(e['repeated_frames'] for e in evidence),
        overlap_evidence='whole compressed packet identity plus complete seek counters; game decoder state unconfirmed',
        pre_skip_assumption='312 inherited from existing Ogg policy' if pre_skip == 312 else 'explicit caller value')
    return audio_pcm.wav_bytes(pcm, channels=1), info


def extract_ogg(bank: bytes, stream: dict, channel_index=0, *, skip_policy='zero',
                pre_skip=audio.PRE_SKIP, title='gta6x', max_nodes=music.MAX_NODES,
                max_frames=None, max_input_bytes=None):
    """Remux a checked music interval without decoding or rewriting packets.

    Nonzero mono skips require the existing observed-size, exact-identity
    profile. Stereo nonzero skips remain unsupported. This API is independent
    of the legacy Ogg exporter; its explicit declared-duration granules and
    inherited pre-skip do not establish original game alignment.
    """
    from . import audio_ogg

    _policy(skip_policy)
    input_limit = audio_pcm.MAX_INPUT_BYTES if max_input_bytes is None else max_input_bytes
    view = music.inspect_channels(bank, stream, max_nodes=max_nodes,
                                  max_input_bytes=input_limit)
    music._integer(channel_index, 'channel index', maximum=len(view['channels'])-1)
    channel = view['channels'][channel_index]
    nonzero = any(span['raw_skip'] for span in channel['spans'])
    if nonzero and skip_policy == 'zero':
        raise music.MusicUnsupportedError(channel['reason'])
    if nonzero and channel['channels_per_record'] == 2:
        raise music.MusicUnsupportedError('stereo nonzero block-skip policy is not validated')
    packets, evidence = _packets(bank, channel)
    result, info = audio_ogg.ogg_opus(packets, channel['frames'],
        channels=channel['channels_per_record'], pre_skip=pre_skip, title=title,
        max_frames=max_frames, max_input_bytes=input_limit)
    info.update(ogg_profile=info['profile'], profile=OGG_PROFILE, skip_policy=skip_policy,
        channel_index=channel_index, channel_id=channel['id'],
        declared_samples=channel['samples'], declared_frames=channel['frames'],
        music_blocks=len(channel['spans']), source_data_sha256=view['source_data_sha256'],
        block_skips=[span['raw_skip'] for span in channel['spans']], packet_overlap=evidence,
        removed_repeated_packets=sum(e['repeated_packets'] for e in evidence),
        removed_repeated_frames=sum(e['repeated_frames'] for e in evidence),
        overlap_evidence='whole compressed packet identity plus complete seek counters; game decoder state unconfirmed',
        pre_skip_assumption='312 inherited from existing Ogg policy' if pre_skip == 312 else 'explicit caller value')
    return result, info
