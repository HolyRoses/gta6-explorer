"""Native level-resource catalogue from bounded source streams and local schemas.

This indexes checksummed PSIN containers and bounded version-122 0DRP metadata.
Storage/schema associations are not placements, entities, geometry or a complete
world decoder. No external backend or inferred cross-file pointer is used.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
from types import SimpleNamespace

from . import anim_resources, psin, psin_blocks, psin_schema, rpf, zlibcarve

MAX_SCAN_BYTES = 64 * 1024 * 1024
MAX_INFLATED_BYTES = 64 * 1024 * 1024
MAX_RESOURCE_BYTES = 16 * 1024 * 1024
PAGE = 65536


class WorldResourceLimitError(ValueError):
    """The complete catalogue is refused rather than returning prefix rows."""


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _fingerprint(value):
    return _digest(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def _psin_metadata(data, consume):
    sections = psin._sections_tile(data)
    if sections is None:
        raise ValueError('PSIN sections do not tile a complete bounded container')
    # Charge table work before the established parsers allocate descriptors.
    consume(1 + sum((s.length - 8 + 15) // 16 for s in sections if s.tag in ('LSCH', 'LENM')))
    position = 8
    while position + 8 <= sections[0].length and data[position:position + 8] != b'pppppppp':
        consume()
        if position + 16 > sections[0].length or data[position + 8:position + 16] != b'\xaa' * 8:
            raise ValueError('unsupported PSIN block table')
        position += 16
    schema = psin_schema.parse_schema(data)  # Includes complete CHKS verification.
    blocks = psin_blocks.parse_blocks(data[:sections[0].length])
    structures = []
    for definition in schema.structures:
        structures.append(dict(hash=f'0x{definition.name_hash:08x}', byte_size=definition.byte_size,
            unknown_words=[definition.unknown_04, definition.unknown_08, definition.unknown_0c, definition.unknown_1c],
            fields=[[f.name_hash, f.data_offset, f.type_word, f.auxiliary] for f in definition.fields]))
    enums = [dict(hash=f'0x{e.name_hash:08x}', unknown_words=[e.unknown_04, e.unknown_14],
        members=[[m.value_bits, m.name_hash, m.unknown_0c] for m in e.members])
        for e in schema.enum_table.definitions]
    return structures, enums, [dict(index=b.index, table_offset=b.table_offset,
        type_hash=f'0x{b.type_hash:08x}', data_offset=b.data_offset, byte_length=b.byte_length)
        for b in blocks], dict(status='checksum_verified', checksum_verified=True,
        source_schema_id=schema.schema_id, scope='complete PSIN container; world roles and values remain unknown')


def _drp_metadata(data, consume, remaining):
    parsed = anim_resources.parse_resource(data, max_nodes=remaining())
    consume(parsed['summary']['nodes'])
    structures = [dict(hash=s['hash'], byte_size=s['byte_size'],
        unknown_words=[int(s[k],16) for k in ('unknown_04','unknown_08','unknown_0c')] + [s['unknown_1c']],
        fields=[[int(f['hash'],16),f['field_offset'],int(f['type_word'],16),int(f['unknown_0c'],16)]
                for f in s['fields']]) for s in parsed['structures']]
    enums = [dict(hash=e['hash'], unknown_words=[int(e['unknown_04'],16),int(e['unknown_14'],16)],
        members=[[int(m['value_bits'],16),int(m['hash'],16),int(m['unknown_0c'],16)] for m in e['members']])
        for e in parsed['enums']]
    return structures, enums, parsed['blocks'], dict(status='partial', checksum_verified=False,
        scope='bounded single-stream 0DRP metadata only; complete resource endpoint, world roles and values unverified')


def inspect_sources(paths, *, start=None, scan_bytes=8 * 1024 * 1024,
                    max_nodes=100000, max_resources=0, max_inflated_bytes=MAX_INFLATED_BYTES,
                    with_schemas=False, dictionary=None, structure_hash=None,
                    field_hash=None, type_word=None, with_links=False,
                    with_extent_diagnostics=False, with_primitive_layouts=False,
                    with_reference_context=False, context_records=(), raw_resources=False,
                    with_value_words=False):
    """Return source-addressed schema/block relationships without a backend.

    Only exact existing PSIN page framing is joined. A 0DRP stream is never joined
    to adjacent opaque data. Unknown streams and recognized-start refusals retain
    their physical identities. Node/inflation failure raises with no catalogue;
    local format refusals preserve independent resource observations.
    Raw mode requires complete files at offset zero, subject to the same source,
    resource and decoded-byte budgets; separate raw inputs are never joined.
    """
    if type(raw_resources) is not bool:
        raise ValueError('native-world raw_resources must be boolean')
    if type(with_value_words) is not bool:
        raise ValueError('native-world with_value_words must be boolean')
    with_links = with_links or with_value_words
    if raw_resources and start not in (None, 0):
        raise ValueError('native-world raw resource input requires a whole file at offset zero')
    for value, label, minimum, maximum in ((scan_bytes,'scan byte limit',1,MAX_SCAN_BYTES),
        (max_nodes,'node limit',1,2_000_000),(max_resources,'resource limit',0,1_000_000),
        (max_inflated_bytes,'inflated byte limit',1,MAX_INFLATED_BYTES)):
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f'invalid native-world {label}')
    if start is not None and (type(start) is not int or start < 0):
        raise ValueError('native-world start must be a nonnegative integer')
    if not isinstance(paths, (list, tuple)) or not paths:
        raise ValueError('native-world catalogue requires input paths')
    for value in (structure_hash, field_hash, type_word):
        if value is not None and (type(value) is not int or not 0 <= value <= 0xffffffff):
            raise ValueError('native-world schema queries require unsigned 32-bit words')
    if dictionary is not None and (not isinstance(dictionary, dict) or
            any(not isinstance(dictionary.get(k, {}), dict) for k in ('hashes', 'exact'))):
        raise ValueError('native-world names require hash/exact dictionary objects')
    if (not isinstance(context_records, (list, tuple)) or len(context_records) > 32 or
            any(not isinstance(pair, (list, tuple)) or len(pair) != 2 or
                any(type(v) is not int or not 0 <= v <= 0xffffffff for v in pair)
                for pair in context_records)):
        raise ValueError('native-world context queries require at most 32 unsigned block/record pairs')
    with_reference_context = with_reference_context or bool(context_records)
    with_schemas = with_schemas or dictionary is not None or any(
        value is not None for value in (structure_hash, field_hash, type_word))
    used = inflated = stream_count = hashed_block_bytes = scanned_bytes = coverage_scanned_bytes = 0
    resources = []; archives = []; unknown = []; refused = []; groups = {}; types = {}
    view_failures = raw_files = raw_input_bytes = 0
    def consume(amount=1):
        nonlocal used
        if amount > max_nodes - used:
            raise WorldResourceLimitError('native-world catalogue exceeds shared node budget')
        used += amount
    def remaining():return max_nodes - used
    def consume_coverage_bytes(amount):
        nonlocal coverage_scanned_bytes
        if type(amount) is not int or amount < 0:
            raise ValueError('invalid native-world coverage byte-work charge')
        if amount > MAX_INFLATED_BYTES - coverage_scanned_bytes:
            raise WorldResourceLimitError('native-world coverage exceeds shared byte-work budget')
        coverage_scanned_bytes += amount
    consume()

    def source(file, blob):
        if raw_resources:
            return dict(file=file, offset=0, encoding='raw', stored_bytes=len(blob.data),
                sha256=_digest(blob.data), offset_space='absolute source file bytes')
        return dict(file=file, offset=blob.offset, compressed_bytes=blob.compressed,
            inflated_bytes=len(blob.data), sha256=_digest(blob.data),
            offset_space='absolute compressed archive bytes')

    def unclassified(file, blob, reason='no supported native metadata header'):
        consume();unknown.append(dict(source(file,blob),reason=reason))

    def add(file, pieces, data, kind):
        nonlocal hashed_block_bytes, view_failures
        consume()
        views = {}
        if with_extent_diagnostics:
            if kind != '0drp':
                views['extent_diagnostics'] = dict(status='unsupported', reason='extent diagnostics apply only to 0DRP metadata')
            else:
                from . import world_framing
                try:
                    view = world_framing.inspect_metadata_extent(data, max_nodes=remaining())
                    consume(view['nodes']); views['extent_diagnostics'] = view
                except WorldResourceLimitError:
                    raise
                except anim_resources.ResourceLimitError as exc:
                    raise WorldResourceLimitError(str(exc)) from exc
                except ValueError as exc:
                    consume(getattr(exc, 'nodes', 0))
                    views['extent_diagnostics'] = dict(status='refused', reason=str(exc))
                    view_failures += 1
                else:
                    from . import world_coverage
                    try:
                        view['coverage'] = world_coverage.inspect(data, view, consume=consume,
                            consume_bytes=consume_coverage_bytes)
                    except WorldResourceLimitError:
                        raise
                    except ValueError as exc:
                        view['coverage'] = dict(status='refused', reason=str(exc))
                        view_failures += 1
        try:
            if kind == 'psin':
                definitions, enums, blocks, state = _psin_metadata(data,consume)
            else:
                definitions, enums, blocks, state = _drp_metadata(data,consume,remaining)
        except (WorldResourceLimitError, anim_resources.ResourceLimitError) as exc:
            raise WorldResourceLimitError(str(exc)) from exc
        except ValueError as exc:
            refused.append(dict(source=source(file,pieces[0]),kind=kind,reason=str(exc),
                segments=[source(file,p) for p in pieces], **views));return
        if raw_resources:
            state.update(input_encoding='raw', complete_format=(kind == 'psin'),
                         archive_allocation_endpoint=None)
            if kind == '0drp':
                state['scope'] = ('bounded direct-file 0DRP metadata prefix only; complete resource '
                                  'endpoint, world roles and values unverified')
        declaration = dict(format=kind, structures=definitions, enums=enums)
        group_id = _fingerprint(declaration)
        resource_index = len(resources)
        digest = _digest(data)
        identity = f'{file}@0x{pieces[0].offset:x}:{digest}'
        if group_id not in groups:
            consume(1 + len(definitions) + len(enums))
            groups[group_id] = dict(id=group_id,format=kind,resource_indices=[],
                structures=[dict(index=i,hash=d['hash'],byte_size=d['byte_size'],
                    field_count=len(d['fields']),variant_id=_fingerprint(dict(format=kind,definition=d)))
                    for i,d in enumerate(definitions)],
                enums=[dict(index=i,hash=e['hash'],member_count=len(e['members'])) for i,e in enumerate(enums)])
        if with_schemas:
            from . import world_schemas
            try:
                view = world_schemas.inspect_resource(data, kind, definitions, enums,
                    consume=consume, dictionary=dictionary, structure_hash=structure_hash,
                    field_hash=field_hash, type_word=type_word)
                groups[group_id].setdefault('schema_view', view['declarations'])
                views['schema_occurrences'] = view['occurrences']
                views['schema_summary'] = view['summary']
            except WorldResourceLimitError:
                raise
            except ValueError as exc:
                views['schema_occurrences'] = dict(status='refused', reason=str(exc))
                view_failures += 1
        if with_links:
            if kind != '0drp':
                views['local_links'] = dict(status='unsupported', reason='no native PSIN world body-reference profile established')
                if with_value_words:
                    views['value_words'] = dict(status='unsupported', reason='raw value-word inspection supports the bounded 0DRP profile only')
            else:
                from . import world_links
                try:
                    views['local_links'] = world_links.inspect(data, definitions, blocks, consume=consume)
                except WorldResourceLimitError:
                    raise
                except ValueError as exc:
                    views['local_links'] = dict(status='refused', reason=str(exc))
                    view_failures += 1
                else:
                    from . import world_containers
                    try:
                        views['local_containers'] = world_containers.inspect(
                            data, definitions, blocks, links=views['local_links'], consume=consume)
                    except WorldResourceLimitError:
                        raise
                    except ValueError as exc:
                        views['local_containers'] = dict(status='refused', reason=str(exc))
                        view_failures += 1
                    else:
                        from . import world_values
                        try:
                            views['local_value_sequences'] = world_values.inspect(
                                data, definitions, blocks, links=views['local_links'], consume=consume)
                        except WorldResourceLimitError:
                            raise
                        except ValueError as exc:
                            views['local_value_sequences'] = dict(status='refused', reason=str(exc))
                            view_failures += 1
                        else:
                            if with_value_words:
                                from . import world_words
                                try:
                                    views['value_words'] = world_words.inspect(data, definitions, blocks,
                                        links=views['local_links'], consume=consume, dictionary=dictionary)
                                except WorldResourceLimitError:
                                    raise
                                except ValueError as exc:
                                    views['value_words'] = dict(status='refused', reason=str(exc))
                                    view_failures += 1
        if with_primitive_layouts:
            if kind != '0drp':
                views['primitive_layouts'] = dict(status='unsupported',
                    reason='no native PSIN world primitive-pool profile established')
            else:
                from . import world_primitives
                try:
                    views['primitive_layouts'] = world_primitives.inspect(
                        data, definitions, blocks, consume=consume)
                except WorldResourceLimitError:
                    raise
                except ValueError as exc:
                    views['primitive_layouts'] = dict(status='refused', reason=str(exc))
                    view_failures += 1
        if with_reference_context:
            if kind != '0drp':
                views['reference_context'] = dict(status='unsupported',
                    reason='no native PSIN world reference-context profile established')
            elif views.get('local_links', {}).get('status') == 'refused':
                views['reference_context'] = dict(status='refused',
                    reason='local counted-reference view refused; ancestry unavailable')
                view_failures += 1
            else:
                from . import world_owners
                try:
                    views['reference_context'] = world_owners.inspect(data, definitions, blocks,
                        consume=consume, links=views.get('local_links'), queries=context_records)
                except WorldResourceLimitError:
                    raise
                except ValueError as exc:
                    views['reference_context'] = dict(status='refused', reason=str(exc))
                    view_failures += 1
                else:
                    from . import world_header_context
                    try:
                        views['reference_context']['header_context'] = world_header_context.inspect(
                            data, definitions, blocks, consume=consume)
                    except WorldResourceLimitError:
                        raise
                    except ValueError as exc:
                        views['reference_context']['header_context'] = dict(status='refused', reason=str(exc))
                        view_failures += 1
        consume();groups[group_id]['resource_indices'].append(resource_index)
        local = {}
        for i, definition in enumerate(definitions):
            consume();local.setdefault(definition['hash'],[]).append((i,definition))
            key = kind,definition['hash'];variant = _fingerprint(dict(format=kind,definition=definition))
            if key not in types:consume();types[key]={}
            if variant not in types[key]:consume();types[key][variant]=[]
            consume();types[key][variant].append(dict(resource_index=resource_index,structure_index=i))
        associations=[];span_hashes={}
        for block in blocks:
            consume();row=dict(block_index=block['index'],table_offset=block['table_offset'],
                type_hash=block['type_hash'],data_offset=block['data_offset'],byte_length=block['byte_length'],
                status='unresolved')
            candidates=local.get(block['type_hash'],[])
            at,length=block['data_offset'],block['byte_length']
            if at is not None and length:
                key=at,length
                if key not in span_hashes:
                    if length>max_inflated_bytes-hashed_block_bytes:
                        raise WorldResourceLimitError('native-world block hashing exceeds shared byte-work budget')
                    hashed_block_bytes+=length
                    span_hashes[key]=_digest(memoryview(data)[at:at+length])
                row['sha256']=span_hashes[key]
            if len(candidates)!=1:
                row['reason']='missing local structure' if not candidates else 'ambiguous local structure'
            else:
                i,definition=candidates[0];width=definition['byte_size']
                if width<=0 or block['byte_length']<=0 or block['byte_length']%width:
                    row['reason']='block does not tile a positive local structure extent'
                else:
                    row.update(status='schema_tiled_storage',schema_group_id=group_id,structure_index=i,
                        structure_variant_id=groups[group_id]['structures'][i]['variant_id'],
                        stride=width,record_count=block['byte_length']//width,
                        interpretation='counted local storage groups only; no entity or world-object meaning')
            associations.append(row)
        consume(len(pieces))
        resources.append(dict(state,index=resource_index,id=identity,format=kind,source_file=file,
            offset=pieces[0].offset,sha256=digest,inflated_bytes=len(data),schema_group_id=group_id,
            offset_space=('source file bytes; complete direct input begins at zero' if raw_resources else
                          'decompressed resource; archive positions are in segments'),
            segments=[source(file,p) for p in pieces],blocks=associations, **views))

    stop=False
    for path in paths:
        consume();file=os.path.realpath(os.fspath(path));size=os.path.getsize(file)
        if raw_resources:
            # Read the complete explicit file or refuse before reading any prefix.
            # This is not archive carving and never seeks a convenient inner magic.
            if size > MAX_RESOURCE_BYTES:
                raise WorldResourceLimitError('native-world raw resource exceeds per-file byte limit')
            if size > scan_bytes or size > MAX_SCAN_BYTES-scanned_bytes:
                raise WorldResourceLimitError('native-world raw resource exceeds shared source byte budget')
            if size > max_inflated_bytes-raw_input_bytes:
                raise WorldResourceLimitError('native-world raw resources exceed shared decoded byte budget')
            consume(1 + (size+4095)//4096)
            with open(file, 'rb') as handle:
                data = handle.read(size+1)
            if len(data) != size:
                raise ValueError('native-world raw source size changed during reading')
            scanned_bytes += size; raw_input_bytes += size; raw_files += 1
            archive = dict(file=file,start=0,end=size,resource_limit_reached=False,streams=0,
                           input_encoding='raw',raw_files=1)
            archives.append(archive)
            piece = SimpleNamespace(offset=0,data=data)
            if data[:4] == b'PSIN':
                add(file,[piece],data,'psin')
            elif data[16:20] == b'0DRP':
                add(file,[piece],data,'0drp')
            else:
                unclassified(file,piece,'no supported native metadata header at the start of the raw file')
            if max_resources and len(resources) >= max_resources:
                archive['resource_limit_reached'] = True
                break
            continue
        begin=start
        if begin is None:
            try:
                header=rpf.read_header(file);begin=header.index_size if header.is_rpf9 else 0
            except (OSError,ValueError):begin=0
        if begin>size:raise ValueError('native-world scan starts beyond the input')
        end=min(size,begin+scan_bytes)
        if end-begin>MAX_SCAN_BYTES-scanned_bytes:
            raise WorldResourceLimitError('native-world scan exceeds shared compressed-byte budget')
        scanned_bytes+=end-begin
        archive=dict(file=file,start=begin,end=end,resource_limit_reached=False,streams=0)
        archives.append(archive)
        def streams():
            nonlocal inflated,stream_count
            for blob in zlibcarve.carve_streams(file,start=begin,length=end-begin,min_out=8,max_out=MAX_RESOURCE_BYTES):
                consume()
                if len(blob.data)>max_inflated_bytes-inflated:
                    raise WorldResourceLimitError('native-world scan exceeds shared inflated-byte budget')
                inflated+=len(blob.data);stream_count+=1;archive['streams']+=1
                yield blob
        iterator=iter(streams());pending=None
        with open(file,'rb') as fh:
            while True:
                blob=pending if pending is not None else next(iterator,None);pending=None
                if blob is None:break
                if blob.data[:4]==b'PSIN':
                    pieces=[blob];total=len(blob.data);assembled=bytearray(blob.data)
                    # A complete first stream needs no adjoining bytes. Otherwise
                    # apply the project's existing exact 64-KiB page grammar.
                    while psin._sections_tile(assembled) is None and len(pieces[-1].data)==PAGE:
                        following=next(iterator,None)
                        if following is None:break
                        previous=pieces[-1];at=previous.offset+previous.compressed;aligned=(at+15)&~15
                        fh.seek(at);padding=fh.read(aligned-at)
                        independent=(following.data[:4] in (b'PSIN',b'RBF0',b'MoVE')
                            or following.data[16:20]==b'0DRP' or following.data.lstrip().startswith(b'<?xml'))
                        if (following.offset!=aligned or any(padding) or len(padding)!=aligned-at
                                or independent or len(following.data)>PAGE):
                            pending=following;break
                        if len(following.data)>MAX_RESOURCE_BYTES-total:
                            raise WorldResourceLimitError('native-world PSIN chain exceeds resource byte budget')
                        total+=len(following.data);pieces.append(following);assembled.extend(following.data)
                    add(file,pieces,bytes(assembled),'psin')
                elif blob.data[16:20]==b'0DRP':
                    add(file,[blob],blob.data,'0drp')
                else:unclassified(file,blob)
                if max_resources and len(resources)>=max_resources:
                    archive['resource_limit_reached']=True;stop=True;break
        if stop:break
    variants=[]
    for (kind,name),entries in sorted(types.items()):
        variants.append(dict(format=kind,type_hash=name,conflict=len(entries)>1,
            variants=[dict(id=key,occurrences=value) for key,value in sorted(entries.items())]))
    blocks=[b for resource in resources for b in resource['blocks']]
    report = dict(format='gta6x-native-world-resources-v1',status='partial' if refused or view_failures else 'complete',
        scope='bounded recognized stream metadata; no placement/entity/geometry decode, archive coverage or cross-file pointer claim',
        archives=archives,resources=resources,schema_groups=list(groups.values()),type_variants=variants,
        unclassified_streams=unknown,refused_streams=refused,
        summary=dict(streams=stream_count,psin_resources=sum(r['format']=='psin'for r in resources),
            drp_resources=sum(r['format']=='0drp'for r in resources),resources=len(resources),
            unclassified_streams=len(unknown),resources_refused=len(refused),blocks=len(blocks),
            blocks_typed=sum(b['status']=='schema_tiled_storage'for b in blocks),
            blocks_unresolved=sum(b['status']!='schema_tiled_storage'for b in blocks),
            typed_records=sum(b.get('record_count',0)for b in blocks),schema_groups=len(groups),
            type_hash_conflicts=sum(v['conflict']for v in variants),metadata_nodes=used,
            scan_window_bytes=scanned_bytes,inflated_bytes=inflated,hashed_block_bytes=hashed_block_bytes))
    if raw_resources:
        report['input_encoding'] = 'raw'
        report['scope'] = ('bounded direct-file native metadata; no carving, resource joining, '
                           'placement/entity/geometry decode or archive allocation claim')
        report['summary'].update(raw_files=raw_files, raw_input_bytes=raw_input_bytes)
    if with_schemas or with_links or with_extent_diagnostics or with_primitive_layouts or with_reference_context:
        report['summary']['views_refused'] = view_failures
    if with_links:
        report['summary']['local_reference_ranges'] = sum(
            r['local_links'].get('summary', {}).get('reference_ranges', 0) for r in resources)
        for source_key, output_key in (('containers','local_container_headers'),
                ('entry_ranges','local_container_entry_ranges'),
                ('entry_record_observations','local_container_entry_records')):
            report['summary'][output_key] = sum(
                r.get('local_containers', {}).get('summary', {}).get(source_key, 0) for r in resources)
        for key in ('value_headers','null_headers','primitive_pool_ranges','primitive_pool_groups','unresolved_pools'):
            output_key = 'local_value_headers' if key == 'value_headers' else 'local_value_' + key
            report['summary'][output_key] = sum(
                r.get('local_value_sequences', {}).get('summary', {}).get(key, 0) for r in resources)
    if with_value_words:
        for key in ('primitive_words','key_slots','preimage_words','preimage_candidates'):
            report['summary']['raw_' + key] = sum(r.get('value_words', {}).get('summary', {}).get(key, 0)
                                                for r in resources)
    if with_primitive_layouts:
        for key in ('primitive_pools', 'primitive_groups'):
            report['summary'][key] = sum(
                r['primitive_layouts'].get('summary', {}).get(key, 0) for r in resources)
    if with_extent_diagnostics:
        report['summary']['coverage_scanned_bytes'] = coverage_scanned_bytes
    return report
