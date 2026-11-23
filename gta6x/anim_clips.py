"""Bounded named clip-record links from direct animation-byte observations.

Only the observed dictionary/node/kind-2 record-prefix profile is supported.
Names are read through checked record references and verified against stored
stem hashes. Unknown class tags, header roles, packed data and curves remain
uninterpreted. No external decoder, title-specific table or game fixture is used.
"""
from __future__ import annotations

import hashlib
import math
import struct

from . import anim_resources as resources, names

BASE = resources.VIRTUAL_BASE
HEADER = 0x70
PREFIX = 0x90


def is_dictionary(data):
    """Recognize candidate framing; invalid attributes are checked by the parser."""
    return (len(data) >= HEADER and data[:8] == bytes(8)
            and data[16:56] == bytes(40) and struct.unpack_from('<I', data, 108)[0] == 2)


def parse_dictionary(data: bytes, *, max_nodes=100000, with_components=False, with_packed_layout=False, with_channels=False, with_storage=False, with_payloads=False, with_bitrows=False, with_lookups=False, with_prefix=False, with_aux_checkpoints=False, with_checkpoint_candidates=False):
    """Return inferred named record links, retaining explicit unresolved members.

    Malformed dictionaries and exhausted budgets raise ValueError without
    prefix output. Unsupported or invalid individual record bindings retain
    their raw node words and a reason. A duration candidate is never a decoded
    curve or independently confirmed time value. No hash-bucket formula or
    complete object size is inferred from this profile.
    """
    if with_checkpoint_candidates:
        with_aux_checkpoints = True
    if with_aux_checkpoints:
        with_prefix = True
    if with_lookups or with_prefix:
        with_bitrows = True
    if with_payloads or with_bitrows:
        with_storage = True
    if with_storage:
        with_channels = True
    if with_channels:
        with_packed_layout = True
    if with_packed_layout:
        with_components = True
    if max_nodes < 1:
        raise resources.ResourceLimitError('clip metadata output exceeds node limit')
    if len(data) > resources.MAX_RESOURCE:
        raise resources.ResourceLimitError('clip dictionary exceeds size limit')
    if not is_dictionary(data):
        raise ValueError('unsupported named clip dictionary header')
    nodes = 1
    payload_hash_cache = {}
    if with_components:
        from . import anim_components

    def consume(n=1):
        nonlocal nodes
        if n > max_nodes - nodes:
            raise resources.ResourceLimitError('clip metadata output exceeds node limit')
        nodes += n

    def span(word, length, label):
        at = word - BASE
        if at < HEADER or length < 0 or at > len(data) - length:
            raise ValueError(f'clip {label} span exceeds dictionary bounds or overlaps header')
        return at

    def string(at):
        word, length, capacity, flags = struct.unpack_from('<QHHI', data, at)
        if capacity != length + 1 or flags != 1 or length == 0:
            raise ValueError('unsupported clip string header')
        pos = span(word, capacity, 'string')
        raw = data[pos:pos + length]
        if data[pos + length] != 0 or any(b < 32 or b > 126 for b in raw):
            raise ValueError('clip string is not exact printable ASCII with a final NUL')
        consume(1 + (length + 63) // 64)
        return dict(value=raw.decode('ascii'), data_offset=pos, byte_length=length,
                    header_data_offset=at, header_bits='0x' + data[at:at + 16][::-1].hex())

    identifier = string(56)
    word, slots, zero, count, flags, reserved, tag, kind = struct.unpack_from('<QIIIIQII', data, 72)
    if not slots or zero or reserved or flags != 0x01000000 or kind != 2:
        raise ValueError('unsupported clip dictionary table attributes')
    table = span(word, slots * 8, 'slot table')
    consume(slots + count * 2)  # Count and bound all node/link observations before allocation.
    heads = list(struct.unpack_from(f'<{slots}Q', data, table))
    seen, entries = set(), []
    for slot, head in enumerate(heads):
        current = head
        while current:
            if current in seen:
                raise ValueError('clip node chain cycles or aliases another visited node')
            if len(seen) >= count:
                raise ValueError('clip node chains exceed the declared entry count')
            seen.add(current)
            at = span(current, 32, 'node')
            key, node_tag, target, following, tail = struct.unpack_from('<IIQQQ', data, at)
            if node_tag != tag or tail:
                raise ValueError('unsupported clip node tag or reserved word')
            entry = dict(index=len(entries), slot_index=slot, node_data_offset=at,
                key=f'0x{key:08x}', unknown_tag=f'0x{node_tag:08x}',
                reference_bits=f'0x{target:016x}', next_reference_bits=f'0x{following:016x}',
                status='unresolved')
            entries.append(entry)
            try:
                rec = span(target, 40, 'record prefix')
                marker = struct.unpack_from('<I', data, rec + 32)[0]
                entry['kind_word'] = marker
                if marker != 2:
                    raise ValueError('unsupported clip record kind; only the observed kind-2 prefix is bound')
                span(target, PREFIX, 'kind-2 record prefix')
                if (data[rec:rec + 16] != bytes(16)
                        or struct.unpack_from('<QQ', data, rec + 16) != (1, BASE)
                        or data[rec + 36:rec + 40] != bytes(4)
                        or data[rec + 80:rec + 88] != bytes(8)
                        or data[rec + 96:rec + 104] != bytes(8)
                        or data[rec + 128:rec + 144] != bytes(16)):
                    raise ValueError('unsupported clip record-prefix attributes')
                if struct.unpack_from('<II', data, rec + 88) != (key, tag):
                    raise ValueError('clip record hash/tag differs from its referring node')
                name = string(rec + 40)
                path = name['value']
                stem = path.rsplit('/', 1)[-1][:-5]
                if not path.startswith('pack:/') or not path.endswith('.clip') or not stem:
                    raise ValueError('record name is not a supported pack clip path')
                if names.joaat(stem) != key:
                    raise ValueError('clip name stem hash differs from the stored node/record key')
                raw = data[rec + 120:rec + 124]
                value = struct.unpack('<f', raw)[0]
                duration = dict(data_offset=rec + 120, value_bits='0x' + raw[::-1].hex(),
                                interpretation='candidate duration; semantic role unconfirmed',
                                status='candidate' if math.isfinite(value) and value >= 0 else 'unresolved')
                if duration['status'] == 'candidate':
                    duration['value'] = value
                else:
                    duration['reason'] = 'nonfinite or negative candidate retained only as bits'
                entry.update(status='record_reference', profile='local_named_clip_prefix_v1',
                             interpretation='inferred', record_data_offset=rec,
                             record_prefix_byte_length=PREFIX, name=name, duration_candidate=duration)
                if with_components:
                    entry['components'] = anim_components.resolve(data, rec, consume=consume,
                                                                  hash_cache=payload_hash_cache, with_packed_layout=with_packed_layout, with_channels=with_channels, with_storage=with_storage, with_payloads=with_payloads, with_bitrows=with_bitrows, with_lookups=with_lookups, with_prefix=with_prefix, with_aux_checkpoints=with_aux_checkpoints, with_checkpoint_candidates=with_checkpoint_candidates)
            except resources.ResourceLimitError:
                raise
            except ValueError as exc:
                entry['reason'] = str(exc)
            current = following
    if len(seen) != count:
        raise ValueError('clip node count differs from the declared entry count')
    linked = sum(e['status'] == 'record_reference' for e in entries)
    report = dict(format='gta6x-named-clip-records-v1', status='partial',
        interpretation='Inferred bounded name/node/record-prefix associations; raw tags and '
                       'duration candidates retain unknown semantics. No packed-payload or curve decoding.',
        byte_length=len(data), sha256=hashlib.sha256(data).hexdigest(), identifier=identifier,
        header_bits='0x' + data[:HEADER][::-1].hex(), unknown_08=f'0x{struct.unpack_from("<Q", data, 8)[0]:016x}',
        unknown_tag=f'0x{tag:08x}', slot_table=dict(data_offset=table,
            reference_bits=f'0x{word:016x}', slot_count=slots, declared_entry_count=count,
            heads=[f'0x{head:016x}' for head in heads]), entries=entries,
        summary=dict(nodes=nodes, entries=count, clips_linked=linked, clips_unresolved=count - linked))

    if with_components:
        views = [e['components'] for e in entries if 'components' in e]
        valid = [view for view in views if view['status'] == 'complete']
        report['summary'].update(component_clips_attempted=len(views),
            component_clips_resolved=len(valid), component_clips_unresolved=len(views) - len(valid),
            component_groups=sum(v['group_count'] for v in valid),
            animation_links=sum(v['animation_links'] for v in valid),
            payload_spans=sum(v['payload_spans'] for v in valid))
        report['interpretation'] = ('Inferred name/node/record-prefix and optional component/animation-buffer '
                                    'associations; timing meanings and packed contents remain unconfirmed.')
    if with_packed_layout:
        layouts = [segment['animation']['packed_layout'] for e in entries
                   if e.get('components', {}).get('status') == 'complete'
                   for group in e['components']['groups'] for segment in group['segments']]
        complete = [layout for layout in layouts if layout['status'] == 'complete']
        report['summary'].update(packed_layouts_attempted=len(layouts), packed_layouts_resolved=len(complete),
            packed_layouts_unresolved=len(layouts) - len(complete),
            packed_buffer_layouts=sum(v['buffer_count'] for v in complete),
            channel_binding_rows=sum(v['binding_count'] for v in complete),
            packed_auxiliary_rows=sum(v['auxiliary_row_count'] for v in complete))
        report['interpretation'] = ('Inferred name/component/buffer associations and bounded packed/header/channel-candidate '
                                    'metadata; identifiers, codecs, timing and sample values remain unconfirmed.')
    if with_channels:
        views = [buffer['channel_layout'] for layout in layouts
                 if layout['status'] == 'complete' for buffer in layout['buffers']]
        complete = [view for view in views if view['status'] == 'complete']
        report['summary'].update(channel_layouts_attempted=len(views),
            channel_layouts_resolved=len(complete), channel_layouts_unresolved=len(views) - len(complete),
            channel_groups=sum(view['group_count'] for view in complete),
            channel_slots=sum(view['active_slot_count'] for view in complete))
        report['interpretation'] = ('Inferred bounded clip, buffer and slot-directory associations; '
                                    'group meanings, channel identifiers, codecs, timing and samples remain unknown.')
    if with_storage:
        views = [buffer['storage_layout'] for layout in layouts
                 if layout['status'] == 'complete' for buffer in layout['buffers']]
        complete = [view for view in views if view['status'] == 'complete']
        bits = [view['sample_bit_layout'] for view in complete]
        report['summary'].update(storage_layouts_attempted=len(views),
            storage_layouts_resolved=len(complete), storage_layouts_unresolved=len(views) - len(complete),
            stored_sample_rows=sum(view['sample_rows']['row_count'] for view in complete),
            sample_bit_layouts_resolved=sum(view['status'] == 'complete' for view in bits),
            sample_bit_layouts_unresolved=sum(view['status'] == 'unresolved' for view in bits))
        report['interpretation'] = ('Bounded clip, buffer, slot and fixed-stride storage associations; '
                                    'unsupported bit grammars, codec meanings and sample values remain unknown.')
    if with_payloads:
        views = [buffer['payload_layout'] for layout in layouts
                 if layout['status'] == 'complete' for buffer in layout['buffers']]
        complete = [view for view in views if view['status'] == 'complete']
        report['summary'].update(payload_layouts_attempted=len(views),
            payload_layouts_resolved=len(complete), payload_layouts_unresolved=len(views) - len(complete),
            payload_word_records=sum(view['record_count'] for view in complete),
            payload_words=sum(view['word_count'] for view in complete),
            payload_slot_candidates=sum(view['slot_candidate_count'] for view in complete))
        report['interpretation'] = ('Bounded storage and supported raw payload-word inventories; '
                                    'word/slot associations, numeric types, codec and sample meanings remain unconfirmed.')
    if with_bitrows:
        views = [buffer['bitrow_layout'] for layout in layouts
                 if layout['status'] == 'complete' for buffer in layout['buffers']]
        complete = [view for view in views if view['status'] == 'complete']
        report['summary'].update(bitrow_layouts_attempted=len(views),
            bitrow_layouts_resolved=len(complete), bitrow_layouts_unresolved=len(views)-len(complete),
            bitrow_fixed_records=sum(len(v['fixed_width_records']) for v in complete),
            bitrow_variable_records=sum(len(v['variable_width_records']) for v in complete),
            bitrow_raw_rows=sum(len(v['rows']) for v in complete),
            bitrow_nonzero_views=sum(v['variable_table']['raw_u16_1a'] != 0 for v in complete))
        report['interpretation'] = ('Counted width tables and whole opaque bit rows; per-channel bit offsets, '
                                    'numeric types, quantizers, codecs and timing remain unconfirmed.')
    if with_lookups:
        views = [buffer['lookup_layout'] for layout in layouts
                 if layout['status'] == 'complete' for buffer in layout['buffers']]
        complete = [view for view in views if view['status'] == 'complete']
        report['summary'].update(lookup_layouts_attempted=len(views),
            lookup_layouts_resolved=len(complete), lookup_layouts_unresolved=len(views)-len(complete),
            lookup_records=sum(view['record_count'] for view in complete),
            lookup_entries=sum(view['entry_count'] for view in complete),
            lookup_index_observations=sum(view['index_observation_count'] for view in complete))
        report['interpretation'] = ('Checked source-order indexed-payload candidates; ordering, slot/channel '
                                    'associations, numeric samples, codecs and timing remain unconfirmed.')
    if with_prefix:
        views = [buffer['prefix_layout'] for layout in layouts
                 if layout['status'] == 'complete' for buffer in layout['buffers']]
        complete = [view for view in views if view['status'] == 'complete']
        report['summary'].update(prefix_layouts_attempted=len(views),
            prefix_layouts_resolved=len(complete), prefix_layouts_unresolved=len(views)-len(complete),
            prefix_triplet_records=sum(v['triplet_count'] for v in complete),
            prefix_raw_words=sum(v['word_count'] for v in complete),
            prefix_opaque_records=sum(v['opaque_record_count'] for v in complete))
        report['interpretation'] = ('Bounded mixed prefix word groupings and counted opaque records; '
                                    'individual group/slot/numeric/codec associations remain unknown.')
    if with_aux_checkpoints:
        views = [buffer['auxiliary_checkpoint_layout'] for layout in layouts
                 for buffer in layout.get('buffers', [])]
        accepted = [view for view in views if view['status'] in ('complete','partial')]
        report['summary'].update(aux_checkpoint_layouts_attempted=len(views),
            aux_checkpoint_layouts_resolved=sum(v['status']=='complete' for v in views),
            aux_checkpoint_layouts_partial=sum(v['status']=='partial' for v in views),
            aux_checkpoint_layouts_unresolved=sum(v['status']=='unresolved' for v in views),
            aux_checkpoint_rows_supported=sum(v['summary']['supported_rows'] for v in accepted),
            aux_checkpoint_rows_unsupported=sum(v['summary']['unsupported_rows'] for v in accepted),
            aux_checkpoint_source_records=sum(v['summary']['unique_source_records'] for v in accepted),
            aux_checkpoint_bit_spans=sum(v['summary']['row_bit_checkpoints'] for v in accepted),
            aux_checkpoint_aliases=sum(v['summary']['aliases'] for v in accepted),
            aux_checkpoint_boundary_checkpoints=sum(v['summary'].get('boundary_checkpoints',0) for v in accepted),
            aux_checkpoint_boundary_layouts_unresolved=sum(v['summary'].get('boundary_layouts_unresolved',0) for v in accepted))
        report['interpretation'] = ('Explicit auxiliary source/row-bit checkpoints; compatible directory slots, '
                                    'channels, samples, codecs and timing remain unconfirmed.')
        if with_checkpoint_candidates:
            candidates = [v.get('candidate_layout', {}) for v in accepted]
            for key in ('rows','candidate_sets','candidate_slots','singleton_rows',
                        'ambiguous_rows','unsupported_source_rows'):
                label = 'checkpoint_'+key if key in ('candidate_sets','candidate_slots') else 'checkpoint_candidate_'+key
                report['summary'][label] = sum(
                    v.get('summary', {}).get(key, 0) for v in candidates)
            report['summary']['checkpoint_candidate_layouts_unresolved'] = sum(
                v.get('status') != 'complete' for v in candidates)
    return report


def scan_dictionaries(path, *, start=None, limit=None, max_nodes=100000, with_components=False, with_packed_layout=False, with_channels=False, with_storage=False, with_payloads=False, with_bitrows=False, with_lookups=False, with_prefix=False, with_aux_checkpoints=False, with_checkpoint_candidates=False):
    """Follow dictionary candidates across checked pages, sharing a node budget."""
    if with_checkpoint_candidates:
        with_aux_checkpoints = True
    if with_aux_checkpoints:
        with_prefix = True
    if with_lookups or with_prefix:
        with_bitrows = True
    if with_payloads or with_bitrows:
        with_storage = True
    if with_storage:
        with_channels = True
    if with_channels:
        with_packed_layout = True
    if with_packed_layout:
        with_components = True
    if max_nodes < 0:
        raise ValueError('clip node budget must be nonnegative')
    remaining = max_nodes

    def independent(data):
        # pack:/ pages are observed continuations here, unlike 0DRP framing.
        return (is_dictionary(data) or data[16:20] == b'0DRP'
                or data[:4] in (b'PSIN', b'MoVE', b'RBF0'))

    def ready(data):
        # Naming metadata may fit before an exact-page boundary. This proves
        # only its required spans, not the file/curve payload's full extent.
        try:
            summary = parse_dictionary(data, max_nodes=remaining, with_components=with_components, with_packed_layout=with_packed_layout, with_channels=with_channels, with_storage=with_storage, with_payloads=with_payloads, with_bitrows=with_bitrows, with_lookups=with_lookups, with_prefix=with_prefix, with_aux_checkpoints=with_aux_checkpoints, with_checkpoint_candidates=with_checkpoint_candidates)['summary']
            return (summary['clips_unresolved'] == 0 and not summary.get('component_clips_unresolved', 0)
                    and not summary.get('packed_layouts_unresolved', 0))
        except ValueError:
            return False

    for row, data, error in resources._scan_chains(path, start=start, limit=limit,
            is_start=is_dictionary, independent_start=independent, label='clip dictionary', stop_when=ready):
        if error is None:
            try:
                parsed = parse_dictionary(data, max_nodes=remaining, with_components=with_components, with_packed_layout=with_packed_layout, with_channels=with_channels, with_storage=with_storage, with_payloads=with_payloads, with_bitrows=with_bitrows, with_lookups=with_lookups, with_prefix=with_prefix, with_aux_checkpoints=with_aux_checkpoints, with_checkpoint_candidates=with_checkpoint_candidates)
                remaining -= parsed['summary']['nodes']
                row.update(parsed)
            except ValueError as exc:
                error = str(exc)
        if error is not None:
            row.update(status='refused', reason=error)
        yield row
