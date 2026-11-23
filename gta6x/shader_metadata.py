"""Bounded public DXContainer program headers and SG1 semantic signatures.

No shader instructions, resources, private data or integrity digests are
interpreted. Unknown enums remain numeric; older signature variants remain
explicitly unsupported. Offsets in this report are container-relative.
"""
from __future__ import annotations

import hashlib
import struct

MAX_RECORDS = 65536
MAX_NAME_BYTES = 1024
_STAGES = {0: 'pixel', 1: 'vertex', 2: 'geometry', 3: 'hull', 4: 'domain',
           5: 'compute', 6: 'library', 7: 'ray_generation', 8: 'intersection',
           9: 'any_hit', 10: 'closest_hit', 11: 'miss', 12: 'callable',
           13: 'mesh', 14: 'amplification', 15: 'node'}
_COMPONENTS = {0: 'unknown', 1: 'uint32', 2: 'sint32', 3: 'float32',
               4: 'uint16', 5: 'sint16', 6: 'float16', 7: 'uint64',
               8: 'sint64', 9: 'float64'}
_PRECISIONS = {0: 'default', 1: 'float16', 2: 'float2_8', 3: 'reserved',
               4: 'sint16', 5: 'uint16', 240: 'any16', 241: 'any10'}
_DIRECTIONS = {'ISG1': 'input', 'OSG1': 'output', 'PSG1': 'patch_constant_or_primitive'}
_LEGACY_SIGNATURES = {'ISGN', 'OSGN', 'OSG5', 'PCSG'}


class _LimitError(ValueError):
    pass


def _program(body: bytes, tag: str, origin: int) -> dict:
    if len(body) < 8 or len(body) % 4:
        raise ValueError('program header requires an aligned word sequence')
    version, words = struct.unpack_from('<II', body)
    if words != len(body) // 4:
        raise ValueError('program word count does not match its chunk extent')
    if version & 0xff00:
        raise ValueError('unsupported reserved program-version bits')
    stage = version >> 16
    item = dict(status='complete', tag=tag, data_offset=origin,
                stage_code=stage, stage=_STAGES.get(stage),
                shader_model_major=(version >> 4) & 15,
                shader_model_minor=version & 15,
                version_bits=f'0x{version:08x}', word_count=words,
                interpretation='public program header only; instructions unverified')
    if tag == 'DXIL':
        if len(body) < 24 or body[8:12] != b'DXIL':
            raise ValueError('DXIL program is missing its bitcode header')
        dxil_version, bitcode_offset, bitcode_size = struct.unpack_from('<III', body, 12)
        if bitcode_offset < 16 or bitcode_offset > len(body) - 8:
            raise ValueError('DXIL bitcode offset overlaps its header or exceeds its chunk')
        start = 8 + bitcode_offset
        if bitcode_size < 4 or bitcode_size > len(body) - start:
            raise ValueError('DXIL bitcode size exceeds its bounded chunk')
        end = start + bitcode_size
        if len(body) - end > 3 or any(body[end:]):
            raise ValueError('DXIL program has unsupported trailing data')
        item['bitcode'] = dict(data_offset=origin+start, byte_length=bitcode_size,
            sha256=hashlib.sha256(body[start:end]).hexdigest(),
            interpretation='opaque declared bitcode span; contents unverified')
        item['dxil_version_bits'] = f'0x{dxil_version:08x}'
    return item


def _signature(body: bytes, tag: str, origin: int, spend) -> dict:
    if len(body) < 8:
        raise ValueError('signature header is truncated')
    count, first = struct.unpack_from('<II', body)
    if first < 8 or first > len(body) or first % 4:
        raise ValueError('signature parameter offset overlaps its header or is unaligned')
    if count > (len(body) - first) // 32:
        raise ValueError('signature parameter count exceeds its chunk')
    spend(count)
    strings = first + count * 32
    names = {}
    parameters = []
    last_stream = 0
    for i in range(count):
        at = first + i * 32
        stream, name_at, index, system, component, register, mask, usage, reserved, precision = (
            struct.unpack_from('<6IBBHI', body, at))
        if stream < last_stream:
            raise ValueError('signature streams are not in nondecreasing order')
        last_stream = stream
        if reserved:
            raise ValueError('signature parameter has unsupported reserved bits')
        if mask & 0xf0:
            raise ValueError('signature allocation mask exceeds four components')
        if name_at == 0:
            name = None
        else:
            if name_at < strings or name_at >= len(body):
                raise ValueError('signature name overlaps parameter records or exceeds its chunk')
            if name_at not in names:
                stop = body.find(b'\0', name_at, min(len(body), name_at+MAX_NAME_BYTES+1))
                if stop < 0:
                    raise ValueError('signature name is unterminated or exceeds its byte limit')
                raw = body[name_at:stop]
                if any(c < 32 or c > 126 for c in raw):
                    raise ValueError('signature name has unsupported non-ASCII bytes')
                names[name_at] = raw.decode('ascii')
            name = names[name_at]
        parameter = dict(ordinal=i, data_offset=origin+at, stream=stream,
            semantic_name=name, name_offset=name_at, semantic_index=index,
            system_value_code=system, component_type_code=component,
            component_type=_COMPONENTS.get(component), register=register,
            mask=mask, usage_mask=usage, reserved_bits=reserved,
            minimum_precision_code=precision, minimum_precision=_PRECISIONS.get(precision))
        if tag == 'ISG1':
            parameter['usage_mask_meaning'] = 'always_reads'
        elif tag == 'OSG1':
            parameter['usage_mask_meaning'] = 'never_writes'
        else:
            parameter['usage_mask_meaning'] = 'depends on shader stage; retained raw'
        parameters.append(parameter)
    return dict(status='complete', tag=tag, direction=_DIRECTIONS[tag],
                data_offset=origin, parameter_count=count, first_parameter_offset=first,
                parameters=parameters)


def inspect(data: bytes, *, max_records: int = 4096) -> dict:
    """Return bounded metadata; failures preserve extraction independently.

    The budget counts each chunk inventory, program/signature header and
    signature parameter. Budget or outer-container failure is atomic. A bad
    known chunk has no prefix rows; other independently bounded chunks survive.
    A complete view only covers the public headers supported here, not shader
    validity, private chunk contents or checksum verification.
    """
    from .shaders import validate_dxbc
    result = dict(status='unresolved', chunks=[], programs=[], signatures=[],
                  record_count=0, reasons=[], integrity_hash_verified=False,
                  scope='program headers and SG1 signatures; no instruction or resource decoding')
    if type(max_records) is not int or not 1 <= max_records <= MAX_RECORDS:
        result['reasons'] = [f'max_records must be an integer from 1 to {MAX_RECORDS}']
        return result
    if not isinstance(data, bytes) or not validate_dxbc(data):
        result['reasons'] = ['invalid or unsupported DXBC container structure']
        return result
    used = 0

    def spend(n=1):
        nonlocal used
        if used + n > max_records:
            raise _LimitError('shader metadata record budget exceeded')
        used += n

    chunks, programs, signatures, reasons = [], [], [], []
    try:
        count = struct.unpack_from('<I', data, 28)[0]
        spend(count)
        for i in range(count):
            at = struct.unpack_from('<I', data, 32+4*i)[0]
            tag = data[at:at+4].decode('ascii')
            size = struct.unpack_from('<I', data, at+4)[0]
            origin = at+8
            body = data[origin:origin+size]
            chunk = dict(ordinal=i, tag=tag, header_offset=at, data_offset=origin,
                         byte_length=size, sha256=hashlib.sha256(body).hexdigest(),
                         status='opaque')
            chunks.append(chunk)
            try:
                if tag in ('SHDR', 'SHEX', 'DXIL'):
                    spend()
                    programs.append(_program(body, tag, origin))
                    chunk['status'] = 'complete'
                elif tag in _DIRECTIONS:
                    spend()
                    signatures.append(_signature(body, tag, origin, spend))
                    chunk['status'] = 'complete'
                elif tag in _LEGACY_SIGNATURES:
                    raise ValueError('legacy signature variant is not supported by this metadata view')
            except _LimitError:
                raise
            except ValueError as exc:
                chunk.update(status='unresolved', reason=str(exc))
                reasons.append(f'{tag} chunk {i}: {exc}')
        if len(programs) > 1:
            reasons.append('multiple program headers retained without selecting an authoritative program')
        directions = [s['direction'] for s in signatures]
        if len(set(directions)) != len(directions):
            reasons.append('multiple signatures for one direction retained without choosing one')
        result.update(status='partial' if reasons else 'complete', chunks=chunks,
                      programs=programs, signatures=signatures, record_count=used, reasons=reasons)
    except _LimitError as exc:
        result['reasons'] = [str(exc)]
    return result
