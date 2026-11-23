"""Bounded public DXContainer program, signature and PSV0 metadata.

No shader instructions, game resource names, private data or integrity digests
are interpreted. PSV0 reads declared runtime/resource table prefixes only;
signature/mask suffixes remain opaque. Unknown enums remain numeric.
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
_RESOURCE_TYPES = {0:'invalid',1:'sampler',2:'constant_buffer',3:'typed_srv',4:'raw_srv',
                   5:'structured_srv',6:'typed_uav',7:'raw_uav',8:'structured_uav',9:'counter_structured_uav'}
_RESOURCE_KINDS = {0:'invalid',1:'texture_1d',2:'texture_2d',3:'texture_2d_ms',4:'texture_3d',
    5:'texture_cube',6:'texture_1d_array',7:'texture_2d_array',8:'texture_2d_ms_array',
    9:'texture_cube_array',10:'typed_buffer',11:'raw_buffer',12:'structured_buffer',
    13:'constant_buffer',14:'sampler',15:'texture_buffer',16:'raytracing_acceleration_structure',
    17:'feedback_texture_2d',18:'feedback_texture_2d_array'}


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


def _pipeline(body: bytes, origin: int, spend) -> dict:
    """Read additive public PSV0 layouts, never infer a game binding name."""
    if len(body)<32:raise ValueError('PSV0 runtime header is truncated')
    size=struct.unpack_from('<I',body)[0]
    if size<24 or size%4 or size>len(body)-8:
        raise ValueError('PSV0 runtime extent is too short, unaligned or escapes its chunk')
    prefix=next(n for n in (52,48,36,24) if n<=size)
    version={24:0,36:1,48:2,52:3}[prefix]
    runtime=body[4:4+size]
    lo,hi=struct.unpack_from('<II',runtime,16)
    info=dict(data_offset=origin+4,byte_length=size,known_prefix_bytes=prefix,
        known_prefix_version=version,declared_size_is_known=size in (24,36,48,52),
        stage_union_bits='0x'+runtime[:16][::-1].hex(),minimum_wave_lanes=lo,maximum_wave_lanes=hi)
    if size>prefix:
        info['unknown_extension']=dict(data_offset=origin+4+prefix,byte_length=size-prefix,
            sha256=hashlib.sha256(runtime[prefix:]).hexdigest())
    if version>=1:
        stage=runtime[24]
        info.update(stage_code=stage,stage=_STAGES.get(stage),uses_view_id_raw=runtime[25],
            extra_stage_bits='0x'+runtime[26:28][::-1].hex(),
            input_signature_elements=runtime[28],output_signature_elements=runtime[29],
            patch_or_primitive_signature_elements=runtime[30],input_vectors=runtime[31],
            output_vectors=list(runtime[32:36]))
        if stage==13:
            shared,dependent,payload,vertices,primitives=struct.unpack_from('<IIIHH',runtime)
            info['mesh']=dict(group_shared_bytes=shared,view_id_dependent_shared_bytes=dependent,
                payload_bytes=payload,max_output_vertices=vertices,max_output_primitives=primitives)
        elif stage==1:info['vertex']=dict(output_position_present_raw=runtime[0])
        elif stage==0:info['pixel']=dict(depth_output_raw=runtime[0],sample_frequency_raw=runtime[1])
    if version>=2:info['thread_group_dimensions']=list(struct.unpack_from('<III',runtime,36))
    if version>=3:
        info['entry_name_offset']=struct.unpack_from('<I',runtime,48)[0]
        info['entry_name_status']='unresolved; PSV0 string/signature suffix is not interpreted'
    cursor=4+size;count=struct.unpack_from('<I',body,cursor)[0];cursor+=4
    bindings=[];stride=None
    if count:
        if cursor+4>len(body):raise ValueError('PSV0 resource stride is truncated')
        stride=struct.unpack_from('<I',body,cursor)[0];cursor+=4
        if stride<16 or stride%4 or count>(len(body)-cursor)//stride:
            raise ValueError('PSV0 resource count/stride exceeds its bounded table')
        spend(count)
        for i in range(count):
            at=cursor+i*stride;typ,space,lower,upper=struct.unpack_from('<4I',body,at)
            if lower>upper:raise ValueError('PSV0 resource register range is reversed')
            known=24 if stride>=24 else 16
            row=dict(index=i,data_offset=origin+at,byte_length=stride,type_code=typ,
                resource_type=_RESOURCE_TYPES.get(typ),register_space=space,
                lower_bound=lower,upper_bound=upper,upper_bound_is_unbounded=upper==0xffffffff)
            if known==24:
                kind,flags=struct.unpack_from('<II',body,at+16)
                row.update(kind_code=kind,resource_kind=_RESOURCE_KINDS.get(kind),flags_bits=f'0x{flags:08x}',
                    uses_atomic64=bool(flags&1),unknown_flag_bits=f'0x{flags&~1:08x}')
            if stride>known:
                row['unknown_extension']=dict(data_offset=origin+at+known,byte_length=stride-known,
                    sha256=hashlib.sha256(body[at+known:at+stride]).hexdigest())
            bindings.append(row)
        cursor+=count*stride
    if size==24 and cursor!=len(body):raise ValueError('PSV0 version-zero table has trailing data')
    return dict(status='complete',tag='PSV0',data_offset=origin,runtime_info=info,
        resource_count=count,resource_stride=stride,resource_bindings=bindings,
        parsed_prefix_bytes=cursor,opaque_suffix=dict(data_offset=origin+cursor,
            byte_length=len(body)-cursor,sha256=hashlib.sha256(body[cursor:]).hexdigest()),
        scope='public runtime/resource-table prefix only; signatures, masks, names and binding-to-game identities unresolved')


def inspect(data: bytes, *, max_records: int = 4096, with_psv_signatures: bool = False,
            with_psv_masks: bool = False, with_features: bool = False) -> dict:
    """Return bounded metadata; failures preserve extraction independently.

    The budget counts each chunk inventory, program/signature header and
    signature parameter. Budget or outer-container failure is atomic. A bad
    known chunk has no prefix rows; other independently bounded chunks survive.
    A complete view only covers the public headers supported here, not shader
    validity, private chunk contents or checksum verification.
    """
    from .shaders import validate_dxbc
    result = dict(status='unresolved', chunks=[], programs=[], signatures=[], pipeline_states=[],
                  record_count=0, reasons=[], integrity_hash_verified=False,
                  scope='program headers, SG1 signatures and PSV0 runtime/resource prefixes; no instructions or game binding identities')
    if with_features:
        result.update(feature_flags=[], feature_flags_status='unresolved')
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

    chunks, programs, signatures, pipelines, features, reasons = [], [], [], [], [], []
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
                elif tag == 'PSV0':
                    spend()
                    pipeline = _pipeline(body,origin,spend)
                    pipelines.append(pipeline)
                    chunk['status']='complete'
                    if with_psv_signatures or with_psv_masks:
                        from .shader_psv_signatures import inspect as inspect_signatures
                        try:
                            pipeline['signature_layout'] = inspect_signatures(body, origin, pipeline, spend)
                        except _LimitError:
                            raise
                        except ValueError as exc:
                            pipeline['signature_layout'] = dict(status='unresolved', reason=str(exc), signatures=[])
                            raise ValueError('signature tables: '+str(exc))
                    if with_psv_masks:
                        from .shader_psv_masks import inspect as inspect_masks
                        try:
                            pipeline['dependency_layout'] = inspect_masks(
                                body, origin, pipeline, pipeline['signature_layout'], spend)
                        except _LimitError:
                            raise
                        except ValueError as exc:
                            pipeline['dependency_layout'] = dict(status='unresolved', reason=str(exc), tables=[])
                            raise ValueError('dependency masks: '+str(exc))
                elif tag == 'SFI0' and with_features:
                    from .shader_features import inspect as inspect_features
                    spend()
                    features.append(inspect_features(body, origin, spend))
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
        if len(pipelines)>1:reasons.append('multiple PSV0 prefixes retained without choosing one')
        if with_features and len(features)>1:
            reasons.append('multiple SFI0 feature declarations retained without choosing one')
        if len(programs)==1:
            for pipeline in pipelines:
                stage=pipeline['runtime_info'].get('stage_code')
                if stage is not None and stage!=programs[0]['stage_code']:
                    reasons.append('PSV0 stage differs from the unique program header; both retained')
        result.update(status='partial' if reasons else 'complete', chunks=chunks,
                      programs=programs, signatures=signatures,pipeline_states=pipelines, record_count=used, reasons=reasons)
        if with_features:
            parts = sum(c['tag']=='SFI0' for c in chunks)
            feature_status = ('absent' if not parts else 'complete' if parts==len(features)==1
                              else 'partial' if features else 'unresolved')
            result.update(feature_flags=features, feature_flags_status=feature_status)
    except _LimitError as exc:
        result['reasons'] = [str(exc)]
    return result
