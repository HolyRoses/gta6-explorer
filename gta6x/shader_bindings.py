"""Source-backed queries over public PSV resource declarations.

Register ranges describe logical shader bindings. They do not identify game
textures, materials, runtime descriptor heaps or executable shader behavior.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import copy
import hashlib
import struct

from . import shader_metadata

MAX_RECORDS = shader_metadata.MAX_RECORDS
_NAMESPACES = {1: 's', 2: 'b', 3: 't', 4: 't', 5: 't',
               6: 'u', 7: 'u', 8: 'u', 9: 'u'}


class _LimitError(ValueError):
    pass


def inspect(data: bytes, *, stage_code=None, register_space=None,
            register_index=None, type_code=None, max_records=4096,
            with_psv_signatures=False, with_psv_masks=False, with_features=False) -> dict:
    """Query freshly parsed declarations, preserving ambiguity and source spans.

    Filters are optional raw u32 values. A stage filter tests the PSV declaration
    only; a version-zero PSV with no stage field does not borrow a program stage.
    A register query tests inclusive logical ranges, including unbounded ranges.
    All namespaces are searched unless a resource type filter narrows the query.

    One budget covers underlying metadata, every declaration examined, emitted
    rows, and range-overlap diagnostics. Filters cannot hide work or malformed
    late rows. Budget failure is atomic. Overlap diagnostics cover the complete
    declaration tables, not only matching rows, and do not select a declaration.
    """
    query = dict(stage_code=stage_code, register_space=register_space,
                 register_index=register_index, type_code=type_code)
    result = dict(status='unresolved', source_sha256=None, query=query,
                  declarations=[], overlaps=[], program_stage_codes=[], metadata=None,
                  summary={}, record_count=0, reasons=[], integrity_hash_verified=False,
                  scope='public logical binding declarations; no game resource or runtime heap identities')
    if type(max_records) is not int or not 1 <= max_records <= MAX_RECORDS:
        result['reasons'] = [f'max_records must be an integer from 1 to {MAX_RECORDS}']
        return result
    if any(type(v) is not bool for v in (with_psv_signatures, with_psv_masks, with_features)):
        result['reasons'] = ['metadata options must be booleans']
        return result
    if any(v is not None and (type(v) is not int or not 0 <= v <= 0xffffffff)
           for v in query.values()):
        result['reasons'] = ['binding filters must be unsigned 32-bit integers']
        return result
    if not isinstance(data, bytes):
        result['reasons'] = ['shader source must be immutable bytes']
        return result
    result['source_sha256'] = hashlib.sha256(data).hexdigest()
    metadata = shader_metadata.inspect(data, max_records=max_records,
        with_psv_signatures=with_psv_signatures, with_psv_masks=with_psv_masks, with_features=with_features)
    if metadata['status'] == 'unresolved':
        result['reasons'] = list(metadata['reasons'])
        return result
    used = metadata['record_count']

    def spend(n=1):
        nonlocal used
        if n > max_records - used:
            raise _LimitError('shader binding record budget exceeded')
        used += n

    try:
        declarations, overlaps = [], []
        counts = Counter()
        types, stages, spaces = Counter(), Counter(), Counter()
        for pipeline_index, pipeline in enumerate(metadata['pipeline_states']):
            stage = pipeline['runtime_info'].get('stage_code')
            groups = defaultdict(list)
            for original in pipeline['resource_bindings']:
                spend()
                at, size = original['data_offset'], original['byte_length']
                expected = (original['type_code'], original['register_space'],
                            original['lower_bound'], original['upper_bound'])
                if struct.unpack_from('<4I', data, at) != expected:
                    raise ValueError('resource declaration differs from its original source words')
                if 'kind_code' in original:
                    extra = (original['kind_code'], int(original['flags_bits'], 16))
                    if struct.unpack_from('<II', data, at + 16) != extra:
                        raise ValueError('extended resource declaration differs from its source words')
                row = copy.deepcopy(original)
                namespace = _NAMESPACES.get(row['type_code'])
                row.update(pipeline_index=pipeline_index, pipeline_data_offset=pipeline['data_offset'],
                           declared_stage_code=stage, register_namespace=namespace,
                           source_row_sha256=hashlib.sha256(data[at:at+size]).hexdigest())
                counts['declaration_count'] += 1
                counts['unknown_type_count'] += row['resource_type'] is None
                counts['unknown_stage_count'] += pipeline['runtime_info'].get('stage') is None
                types[row['type_code']] += 1
                stages[stage] += 1
                spaces[row['register_space']] += 1
                matches = ((stage_code is None or stage == stage_code)
                           and (register_space is None or row['register_space'] == register_space)
                           and (register_index is None or row['lower_bound'] <= register_index <= row['upper_bound'])
                           and (type_code is None or row['type_code'] == type_code))
                if matches:
                    spend()
                    declarations.append(row)
                # Unknown resource types are compared only with their exact raw
                # type code; they are never assigned to a known register namespace.
                key = (namespace if namespace is not None else ('raw_type', row['type_code']),
                       row['register_space'])
                groups[key].append(row)
            for rows in groups.values():
                ordered = sorted(rows, key=lambda r: (r['lower_bound'], r['index']))
                for i, left in enumerate(ordered):
                    for j in range(i+1, len(ordered)):
                        right = ordered[j]
                        if right['lower_bound'] > left['upper_bound']:
                            break
                        spend()
                        overlaps.append(dict(pipeline_index=pipeline_index,
                            register_namespace=left['register_namespace'],
                            register_space=left['register_space'],
                            left_index=left['index'], right_index=right['index'],
                            left_data_offset=left['data_offset'], right_data_offset=right['data_offset'],
                            lower_bound=max(left['lower_bound'], right['lower_bound']),
                            upper_bound=min(left['upper_bound'], right['upper_bound']),
                            interpretation='overlapping declared logical ranges; no declaration selected'))
        spend()
        psv_count = sum(c['tag'] == 'PSV0' for c in metadata['chunks'])
        reasons = list(metadata['reasons'])
        status = ('unresolved' if psv_count and not metadata['pipeline_states']
                  else 'partial' if reasons else 'complete')
        summary = dict(declaration_count=counts['declaration_count'], matched_count=len(declarations),
            pipeline_count=len(metadata['pipeline_states']), declared_pipeline_count=psv_count,
            unknown_type_count=counts['unknown_type_count'], unknown_stage_count=counts['unknown_stage_count'],
            overlap_count=len(overlaps),
            binding_status='absent' if not psv_count else 'present' if metadata['pipeline_states'] else 'unresolved',
            resource_types=[dict(type_code=k, declarations=v) for k, v in sorted(types.items())],
            stages=[dict(stage_code=k, declarations=stages[k]) for k in sorted(stages, key=lambda k: -1 if k is None else k)],
            register_spaces=[dict(register_space=k, declarations=v) for k, v in sorted(spaces.items())])
        result.update(status=status, declarations=declarations, overlaps=overlaps, summary=summary,
                      program_stage_codes=[p['stage_code'] for p in metadata['programs']],
                      record_count=used, reasons=reasons, metadata=metadata)
    except (_LimitError, ValueError) as exc:
        result['reasons'] = [str(exc)]
    return result
