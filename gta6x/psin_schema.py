"""LSCH/LENM schema browser, independently derived from local PSIN bytes.

LSCH has an eight-byte tagged/BE-length prefix, contiguous 32-byte LE structure
headers and grouped 16-byte LE field descriptors. Header counts account for the
entire section. No GPL implementation, external type table or external backend
is used. Supported type meanings are explicitly inferred, not confirmed.
Numeric words and unresolved attributes are preserved. Instance export is an
explicit bounded option delegated to :mod:`gta6x.psin_instances`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
import struct

from . import names, psin

__all__ = ['SchemaField', 'SchemaStructure', 'Schema', 'parse_lsch', 'parse_schema',
           'EnumMember', 'EnumDefinition', 'EnumTable', 'parse_lenm', 'iter_sources', 'inspect_sources']


def _hex(value: int) -> str:
    return f'0x{value:08x}'


def _matches(dictionary: dict | None, value: int) -> list[dict]:
    if dictionary is None:
        return []
    return [dict(name=name, source=source) for name, source in
            names.lookup(dictionary, f'{value:08x}')]


@dataclass(frozen=True)
class SchemaField:
    section_offset: int
    name_hash: int
    data_offset: int
    type_word: int
    auxiliary: int

    def as_dict(self, dictionary: dict | None = None, *, type_info: dict | None = None) -> dict:
        info = type_info if type_info is not None else _type_info(self)
        return dict(section_offset=self.section_offset, hash=_hex(self.name_hash),
                    name_matches=_matches(dictionary, self.name_hash),
                    data_offset=self.data_offset, type_word=_hex(self.type_word),
                    type_code=self.type_word & 0xffff, type_name=info['name'],
                    base_type_code=self.type_word & 0xff,
                    type_subcode=(self.type_word >> 8) & 0xff,
                    type_info=info,
                    unknown_type_high16=self.type_word >> 16,
                    unknown_0c=_hex(self.auxiliary))


@dataclass
class SchemaStructure:
    section_offset: int
    name_hash: int
    unknown_04: int
    unknown_08: int
    unknown_0c: int
    byte_size: int
    unknown_1c: int
    fields: list[SchemaField] = field(default_factory=list)

    def as_dict(self, dictionary: dict | None = None, *, structure_index=None,
                enum_index=None) -> dict:
        exponent = (self.unknown_08 >> 8) & 0xff
        alignment = (1 << exponent) if exponent <= 4 and self.unknown_08 >> 16 == 0 else None
        if alignment is not None and self.byte_size % alignment:
            alignment = None
        return dict(section_offset=self.section_offset, hash=_hex(self.name_hash),
                    name_matches=_matches(dictionary, self.name_hash),
                    byte_size=self.byte_size,
                    unknown_04=_hex(self.unknown_04), unknown_08=_hex(self.unknown_08),
                    unknown_0c=_hex(self.unknown_0c), unknown_1c=self.unknown_1c,
                    layout_signature_candidate=_hex(self.unknown_04),
                    flags_byte=self.unknown_08 & 0xff,
                    alignment_log2_candidate=exponent,
                    alignment_candidate=alignment,
                    field_count=len(self.fields),
                    fields=[f.as_dict(dictionary, type_info=_type_info(
                        f, self, structure_index, enum_index)) for f in self.fields])


@dataclass(frozen=True)
class EnumMember:
    section_offset: int
    value_bits: int
    name_hash: int
    unknown_0c: int

    def as_dict(self, dictionary: dict | None = None) -> dict:
        signed = self.value_bits - (1 << 64) if self.value_bits >> 63 else self.value_bits
        return dict(section_offset=self.section_offset, hash=_hex(self.name_hash),
                    name_matches=_matches(dictionary, self.name_hash),
                    value_bits=f'0x{self.value_bits:016x}', value_signed=signed,
                    value_unsigned=str(self.value_bits), unknown_0c=_hex(self.unknown_0c))


@dataclass
class EnumDefinition:
    section_offset: int
    name_hash: int
    unknown_04: int
    unknown_14: int
    members: list[EnumMember] = field(default_factory=list)

    def as_dict(self, dictionary: dict | None = None) -> dict:
        return dict(section_offset=self.section_offset, hash=_hex(self.name_hash),
                    name_matches=_matches(dictionary, self.name_hash),
                    unknown_04=_hex(self.unknown_04), unknown_14=_hex(self.unknown_14),
                    member_count=len(self.members),
                    members=[m.as_dict(dictionary) for m in self.members])


@dataclass
class EnumTable:
    byte_length: int
    sha256: str
    definitions: list[EnumDefinition] = field(default_factory=list)


def _index(definitions):
    result = {}
    for definition in definitions:
        result.setdefault(definition.name_hash, []).append(definition)
    return result


def _type_info(f: SchemaField, owner=None, structures=None, enums=None) -> dict:
    """Conservative annotations from measured codes, widths and references.

    No recursive instance interpretation or primitive fallback for unknown
    codes. Context-dependent meanings require unambiguous matching metadata.
    """
    code, upper = f.type_word & 0xffff, f.type_word >> 16
    info = dict(name=None, status='unknown', storage_bytes=None)
    if code in (1, 0x21, 0x4a) and upper == 0 and f.auxiliary == 0:
        name, width = {1: ('bool8', 1), 0x21: ('float32', 4), 0x4a: ('hash32', 4)}[code]
        info.update(name=name, status='inferred', storage_bytes=width)
    elif code == 5 and upper == 0:
        targets = (structures or {}).get(f.auxiliary, [])
        info.update(candidate='embedded_structure', reference_hash=_hex(f.auxiliary),
                    reference_status='resolved' if len(targets) == 1 else
                    'ambiguous' if targets else 'missing')
        if len(targets) == 1:
            info.update(name='embedded_structure', status='inferred',
                        storage_bytes=targets[0].byte_size,
                        structure_definition_offset=targets[0].section_offset)
    elif code == 0x52 and f.auxiliary == 0 and owner is not None:
        if (upper < len(owner.fields) and owner.fields[upper].name_hash == 0x100
                and owner.fields[upper] is not f):
            info.update(name='dynamic_array', status='inferred', storage_bytes=16,
                        element_descriptor_index=upper)
        else:
            info.update(candidate='dynamic_array', reason='unresolved element descriptor')
    elif code == 0x71 and upper == 0 and owner is not None:
        key, value = f.auxiliary & 0xffff, f.auxiliary >> 16
        if all(i < len(owner.fields) and owner.fields[i].name_hash == 0x100
               and owner.fields[i] is not f for i in (key, value)):
            info.update(name='map', status='inferred', storage_bytes=24,
                        key_descriptor_index=key, value_descriptor_index=value)
        else:
            info.update(candidate='map', reason='unresolved key/value descriptors')
    elif code in (0x62, 0x63, 0x65, 0x68):
        targets = (enums or {}).get(f.auxiliary, [])
        info.update(enum_hash=_hex(f.auxiliary),
                    enum_reference_status='resolved' if len(targets) == 1 else
                    'ambiguous' if targets else 'missing',
                    enum_definition_offsets=[e.section_offset for e in targets])
        if len(targets) == 1:
            if code == 0x62 and upper == 0:
                # 64-bit enum records may sign-extend a negative 32-bit value.
                representable = all(m.value_bits <= 0xffffffff or
                                    m.value_bits >= 0xffffffff80000000 for m in targets[0].members)
                if representable:
                    info.update(name='enum32', status='inferred', storage_bytes=4)
                else:
                    info['reason'] = 'enum member does not fit inferred 32-bit storage'
            elif code in (0x65, 0x68) and upper:
                lane = 32 if code == 0x65 else 64
                info.update(name=f'enum_bitset{lane}', status='inferred', bit_count=upper,
                            storage_bytes=((upper + lane - 1) // lane) * (lane // 8))
            # 0x63 is enum-associated, but its width/upper bits are unresolved.
        if info['name'] is None:
            info['candidate'] = 'enum_associated'
    if owner is not None and info['storage_bytes'] is not None:
        if f.data_offset + info['storage_bytes'] > owner.byte_size:
            info.update(name=None, status='unknown', storage_bytes=None,
                        reason='inferred storage would exceed structure bounds')
    if code == 5 and hasattr(structures, 'resolution'):
        info['reference_resolution'] = structures.resolution(f.auxiliary)
    if code in (0x62,0x63,0x65,0x68) and hasattr(enums, 'resolution'):
        info['enum_resolution'] = enums.resolution(f.auxiliary)
    return info


@dataclass
class Schema:
    byte_length: int
    sha256: str
    structures: list[SchemaStructure] = field(default_factory=list)
    enum_table: EnumTable | None = None

    @property
    def schema_id(self) -> str:
        if self.enum_table is None:
            return self.sha256
        return hashlib.sha256(b'gta6x-psin-schema-v2\0' + bytes.fromhex(self.sha256)
                              + bytes.fromhex(self.enum_table.sha256)).hexdigest()

    def as_dict(self, dictionary: dict | None = None, *, registry=None) -> dict:
        enums = self.enum_table.definitions if self.enum_table else []
        structure_index, enum_index = _index(self.structures), _index(enums)
        if registry is not None:
            scope = registry.scope(self)
            structure_index, enum_index = scope.structures, scope.enums
        return dict(id=self.schema_id, status='structural_with_inferred_types',
                    byte_length=self.byte_length, lsch_sha256=self.sha256,
                    lenm_sha256=self.enum_table.sha256 if self.enum_table else None,
                    structure_count=len(self.structures),
                    field_descriptor_count=sum(len(s.fields) for s in self.structures),
                    structures=[s.as_dict(dictionary, structure_index=structure_index,
                                          enum_index=enum_index) for s in self.structures],
                    enum_count=len(enums), enum_member_count=sum(len(e.members) for e in enums),
                    enums=[e.as_dict(dictionary) for e in enums])


def parse_lsch(data: bytes) -> Schema:
    """Parse exactly one LSCH section, or raise ValueError.

    Only structural relationships are enforced. Unknown attributes/type codes
    are retained, including auxiliary descriptors with synthetic hash/id values.
    Field starts are bounded; field widths and instance semantics are unknown.
    """
    if len(data) < 8 or data[:4] != b'LSCH':
        raise ValueError('not an LSCH section')
    if struct.unpack_from('>I', data, 4)[0] != len(data):
        raise ValueError('LSCH length does not match available bytes')
    headers = []
    position = expected = 8
    # Each header increases the accounted length monotonically. Equality marks
    # the header/field boundary, so field bytes are never scanned as headers.
    while expected < len(data):
        if position + 32 > len(data):
            raise ValueError('truncated LSCH structure header')
        name, a, b, c, padding, size, d, count = struct.unpack_from('<4I8sIHH', data, position)
        if padding != b'\xaa' * 8:
            raise ValueError(f'unsupported LSCH header padding at {position:#x}')
        expected += 32 + count * 16
        if expected > len(data):
            raise ValueError('LSCH field counts exceed section length')
        headers.append((SchemaStructure(position, name, a, b, c, size, d), count))
        position += 32
    if expected != len(data):
        raise ValueError('LSCH record counts do not cover section')
    structures = []
    for structure, count in headers:
        for _ in range(count):
            name, offset, type_word, auxiliary = struct.unpack_from('<4I', data, position)
            if offset >= structure.byte_size:
                raise ValueError(f'LSCH field offset exceeds structure size at {position:#x}')
            structure.fields.append(SchemaField(position, name, offset, type_word, auxiliary))
            position += 16
        structures.append(structure)
    if position != len(data):
        raise ValueError('LSCH trailing bytes')
    return Schema(len(data), hashlib.sha256(data).hexdigest(), structures)


def parse_lenm(data: bytes) -> EnumTable:
    """Parse one LENM section without discarding aliases or unknown words.

    Contiguous 24-byte LE headers precede grouped 16-byte members. Values are
    retained as 64 bits; signedness is not inferred from an enum's names.
    """
    if len(data) < 8 or data[:4] != b'LENM':
        raise ValueError('not a LENM section')
    if struct.unpack_from('>I', data, 4)[0] != len(data):
        raise ValueError('LENM length does not match available bytes')
    headers = []
    position = expected = 8
    while expected < len(data):
        if position + 24 > len(data):
            raise ValueError('truncated LENM enum header')
        name, unknown, padding, count, tail = struct.unpack_from('<II8sII', data, position)
        if padding != b'\xee' * 8:
            raise ValueError(f'unsupported LENM header padding at {position:#x}')
        expected += 24 + count * 16
        if expected > len(data):
            raise ValueError('LENM member counts exceed section length')
        headers.append((EnumDefinition(position, name, unknown, tail), count))
        position += 24
    definitions = []
    for definition, count in headers:
        for _ in range(count):
            value, name, unknown = struct.unpack_from('<QII', data, position)
            definition.members.append(EnumMember(position, value, name, unknown))
            position += 16
        definitions.append(definition)
    if position != len(data):
        raise ValueError('LENM trailing bytes')
    return EnumTable(len(data), hashlib.sha256(data).hexdigest(), definitions)


def parse_schema(data: bytes) -> Schema:
    """Parse LSCH and LENM from a complete checksum-verified PSIN container.

    Fragments, standalone bodies and bad checksums are refused. Use parse_lsch
    only for an explicitly supplied standalone section (no checksum claim).
    """
    container = psin.parse_container(data)
    if container is None:
        raise ValueError('schema requires a complete seven-section PSIN container')
    if not container.checksum_verified:
        raise ValueError('PSIN checksum mismatch')
    section = container.section('LSCH')
    assert section is not None
    schema = parse_lsch(data[section.offset:section.offset + section.length])
    section = container.section('LENM')
    assert section is not None
    schema.enum_table = parse_lenm(data[section.offset:section.offset + section.length])
    return schema


def iter_sources(paths, *, limit):
    """Yield bounded raw/joined PSIN inputs and explicit source errors."""
    from . import structured
    for path in paths:
        label = os.path.basename(path)
        try:
            with open(path, 'rb') as handle:
                raw_psin = handle.read(4) == b'PSIN'
                if raw_psin:
                    handle.seek(0)
                    data = handle.read(structured.MAX_OUTPUT + 1)
            if raw_psin:
                if len(data) > structured.MAX_OUTPUT:
                    raise ValueError('PSIN input exceeds resource size limit')
                yield dict(file=label, offset=0, blocks=1), data, None
            else:
                scan_limit = os.path.getsize(path) if limit is None else limit
                for hit in structured.recover(path, limit=scan_limit):
                    if hit.kind == 'psin':
                        source = dict(file=label, offset=hit.offset, blocks=hit.blocks,
                                      segments=hit.segments)
                        if hit.segment_storage:
                            source['segment_storage'] = hit.segment_storage
                        yield source, hit.data, None
        except (OSError, ValueError) as exc:
            yield dict(file=label), None, str(exc)


def inspect_sources(paths: list[str], *, limit: int | None,
                    dictionary: dict | None = None, with_instances: bool = False,
                    with_resource_header: bool = False, with_record_graph: bool = False,
                    with_bucket_maps: bool = False, with_bucket_values: bool = False,
                    with_bucket_pool_spans: bool = False, with_bucket_graph: bool = False,
                    max_nodes: int = 100000, max_depth: int = 16, registry=None) -> dict:
    """Inspect raw PSIN files or complete joined resources inside archives.

    Identical LSCH+LENM pairs share one schema; differing definitions of the
    same hash remain separate. Sources retain identity and refusal reasons.
    Unrecoverable archive fragments are outside structured.recover's results.
    Instance mode shares one node budget across the report; exhausted or
    unsupported resources keep their verified schemas and explicit refusals.
    """
    from . import structured

    if with_bucket_graph:
        with_record_graph = with_bucket_maps = True
    if with_bucket_pool_spans:
        with_bucket_values = True
    if with_bucket_values:
        with_bucket_maps = True
    if with_bucket_maps:
        with_resource_header = True
        if type(max_depth) is not int or not 1 <= max_depth <= 64:
            raise ValueError('bucket-map max_depth must be an integer from 1 to 64')
    if with_record_graph:
        with_instances = with_resource_header = True
        if type(max_depth) is not int:
            raise ValueError('max_depth must be an integer from 1 to 64')
    resources = []
    schemas = {}
    remaining_nodes = max_nodes
    instance_nodes_used = resource_header_nodes_used = record_graph_nodes_used = 0
    bucket_map_nodes_used = 0
    if with_resource_header and (type(max_nodes) is not int or max_nodes < 1):
        raise ValueError('max_nodes must be a positive integer')
    if with_instances and (max_nodes < 1 or not 1 <= max_depth <= 64):
        raise ValueError('max_nodes must be positive and max_depth must be 1..64')

    def add(data: bytes, source: dict) -> None:
        nonlocal remaining_nodes, instance_nodes_used, resource_header_nodes_used, record_graph_nodes_used, bucket_map_nodes_used
        source = dict(source, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
        try:
            schema = parse_schema(data)
        except ValueError as exc:
            resources.append(dict(source, status='refused', error=str(exc)))
            return
        if schema.schema_id not in schemas:
            schemas[schema.schema_id] = schema.as_dict(dictionary, registry=registry)
        result = dict(source, status='ok', checksum_verified=True, schema_id=schema.schema_id)
        if with_instances:
            before = remaining_nodes
            from . import psin_instances
            try:
                if remaining_nodes < 1:
                    raise psin_instances.InstanceLimitError('report instance node budget exhausted')
                result['instances'] = psin_instances.decode_instances(
                    data, dictionary, max_nodes=remaining_nodes, max_depth=max_depth,
                    registry=registry)
                remaining_nodes -= result['instances']['summary']['nodes']
            except psin_instances.InstanceLimitError as exc:
                remaining_nodes = 0
                result['instances'] = dict(status='refused', reason=str(exc))
            except ValueError as exc:
                result['instances'] = dict(status='refused', reason=str(exc))
            instance_nodes_used += before - remaining_nodes
        if with_resource_header:
            from . import psin_resource_header
            before = remaining_nodes
            try:
                result['resource_header'] = psin_resource_header.inspect(data, max_nodes=remaining_nodes)
                remaining_nodes -= result['resource_header']['summary']['nodes']
            except psin_resource_header.ResourceHeaderLimitError as exc:
                remaining_nodes = 0
                result['resource_header'] = dict(status='refused', reason=str(exc))
            except ValueError as exc:
                result['resource_header'] = dict(status='refused', reason=str(exc))
            resource_header_nodes_used += before - remaining_nodes
        def add_graph(bucket_view=None):
            nonlocal remaining_nodes, record_graph_nodes_used
            from . import psin_record_graph
            before = remaining_nodes
            if result['instances'].get('status') == 'refused':
                result['record_graph'] = dict(status='refused', reason='record graph requires an available instance view')
            elif with_bucket_graph and (not isinstance(bucket_view, dict) or bucket_view.get('status') not in ('complete', 'partial')):
                result['record_graph'] = dict(status='refused', reason='bucket graph requires an available bucket-map view')
            else:
                try:
                    if with_bucket_graph and bucket_view.get('source_sha256') != source['sha256']:
                        raise ValueError('bucket graph source hash differs from the verified resource')
                    bucket_options = {'bucket_maps': bucket_view} if with_bucket_graph else {}
                    result['record_graph'] = psin_record_graph.inspect(
                        result['instances'], result.get('resource_header'),
                        max_nodes=remaining_nodes, max_depth=max_depth, **bucket_options)
                    remaining_nodes -= result['record_graph']['summary']['nodes']
                except psin_record_graph.RecordGraphLimitError as exc:
                    remaining_nodes = 0
                    result['record_graph'] = dict(status='refused', reason=str(exc))
                except ValueError as exc:
                    result['record_graph'] = dict(status='refused', reason=str(exc))
            record_graph_nodes_used += before - remaining_nodes
        if with_record_graph and not with_bucket_graph:
            add_graph()
        if with_bucket_maps:
            from . import psin_bucket_maps
            before = remaining_nodes
            try:
                value_options = {'with_values': True} if with_bucket_values else {}
                if with_bucket_pool_spans:
                    value_options['with_pool_spans'] = True
                view = psin_bucket_maps.inspect(data,max_nodes=remaining_nodes,max_depth=max_depth,**value_options)
                remaining_nodes -= view['summary']['nodes']
                header = result.get('resource_header',{})
                anchor = header.get('record_candidate',{}) if header.get('status')=='complete' else {}
                for mapping in view['maps']:
                    mapping['owner_is_lrsc_record_candidate'] = bool(anchor) and all(
                        mapping['owner'][key]==anchor.get(key) for key in ('block_index','record_index','data_offset','byte_length','structure_hash'))
                result['bucket_maps'] = view
            except psin_bucket_maps.BucketMapLimitError as exc:
                remaining_nodes = 0
                result['bucket_maps'] = dict(status='refused',reason=str(exc))
            except ValueError as exc:
                result['bucket_maps'] = dict(status='refused',reason=str(exc))
            bucket_map_nodes_used += before - remaining_nodes
        if with_bucket_graph:
            add_graph(result.get('bucket_maps'))
        resources.append(result)

    for source, data, error in iter_sources(paths, limit=limit):
        if error is not None:
            resources.append(dict(source, status='refused', error=error))
        else:
            add(data, source)
    rows = list(schemas.values())
    summary = dict(resources_inspected=len(resources),
                   resources_verified=sum(r['status'] == 'ok' for r in resources),
                   resources_refused=sum(r['status'] == 'refused' for r in resources),
                   unique_schemas=len(rows),
                   structures=sum(s['structure_count'] for s in rows),
                   field_descriptors=sum(s['field_descriptor_count'] for s in rows),
                   enum_definitions=sum(s['enum_count'] for s in rows),
                   enum_members=sum(s['enum_member_count'] for s in rows))
    if with_instances:
        inspections = [r['instances'] for r in resources if 'instances' in r]
        for status in ('complete', 'partial', 'refused'):
            summary[f'instance_resources_{status}'] = sum(i['status'] == status for i in inspections)
        summary['instance_nodes'] = instance_nodes_used
        summary['instance_values_decoded'] = sum(i.get('summary', {}).get('decoded_values', 0)
                                                for i in inspections)
        for key in ('hash32_arrays_resolved', 'hash32_array_values_decoded',
                    'enum32_arrays_resolved', 'enum32_array_records_linked',
                    'structure_arrays_resolved', 'structure_array_records_linked',
                    'reference_arrays_resolved', 'reference_array_records_linked', 'reference_array_null_entries',
                    'reference_fields_resolved', 'reference_fields_linked', 'reference_fields_null', 'reference_fields_unresolved',
                    'text_reference_fields_attempted', 'text_reference_fields_resolved',
                    'text_reference_fields_unresolved', 'text_reference_pool_entries_linked',
                    'maps_resolved', 'maps_unresolved', 'map_entries_linked'):
            summary['instance_' + key] = sum(i.get('summary', {}).get(key, 0) for i in inspections)
    if with_resource_header:
        headers = [r['resource_header'] for r in resources if 'resource_header' in r]
        for status in ('complete', 'unresolved', 'refused'):
            summary['resource_headers_' + status] = sum(h['status'] == status for h in headers)
        summary['resource_header_nodes'] = resource_header_nodes_used
        summary['resource_header_record_candidates'] = sum(h.get('summary', {}).get('record_candidates', 0)
                                                          for h in headers)
        summary['metadata_nodes'] = max_nodes - remaining_nodes
    if with_record_graph:
        graphs = [r['record_graph'] for r in resources if 'record_graph' in r]
        for status in ('complete', 'partial', 'refused'):
            summary['record_graph_resources_' + status] = sum(g['status'] == status for g in graphs)
        summary['record_graph_nodes'] = record_graph_nodes_used
        for target, source_key in (('records', 'record_nodes'), ('edges', 'record_edges'),
                                   ('reachable_records', 'reachable_records'),
                                   ('unresolved_fields', 'unresolved_fields'),
                                   ('unrepresented_blocks', 'unrepresented_blocks'),
                                   ('depth_limited', 'depth_limited')):
            summary['record_graph_' + target] = sum(g.get('summary', {}).get(source_key, 0) for g in graphs)
        summary['record_graph_unanchored'] = sum(g.get('reachability', {}).get('status') == 'unanchored'
                                                for g in graphs)
        if with_bucket_graph:
            for key in ('bucket_maps_supported','bucket_maps_unresolved',
                        'bucket_reference_edges','bucket_inline_maps_excluded',
                        'bucket_inline_entries_excluded','bucket_scan_partial'):
                summary['record_graph_'+key]=sum(g.get('summary',{}).get(key,0) for g in graphs)
        summary['metadata_nodes'] = max_nodes - remaining_nodes
    if with_bucket_maps:
        views=[r['bucket_maps'] for r in resources if 'bucket_maps' in r]
        for status in ('complete','partial','refused'):
            summary['bucket_map_resources_'+status]=sum(v['status']==status for v in views)
        summary['bucket_map_nodes']=bucket_map_nodes_used
        for key in ('maps_complete','maps_unresolved','entry_links','depth_limited'):
            summary['bucket_'+key]=sum(v.get('summary',{}).get(key,0) for v in views)
        if any('structure_value_spans' in v.get('summary',{}) for v in views):
            summary['bucket_structure_value_spans']=sum(v.get('summary',{}).get('structure_value_spans',0) for v in views)
            summary['bucket_reference_links']=sum(v.get('summary',{}).get('reference_links',
                v.get('summary',{}).get('entry_links',0)) for v in views)
        if with_bucket_values:
            for key in ('bucket_value_records','bucket_value_fields','bucket_value_fields_complete',
                        'bucket_value_fields_unresolved','bucket_value_array_links','bucket_value_reference_links',
                        'bucket_value_nested_maps','bucket_value_nested_maps_unresolved',
                        'bucket_value_map_fields','bucket_value_map_fields_complete','bucket_value_map_links'):
                summary[key]=sum(v.get('summary',{}).get(key,0) for v in views)
        if with_bucket_pool_spans:
            for key in ('bucket_value_pool_fields','bucket_value_pool_spans_complete',
                        'bucket_value_pool_spans_unresolved','bucket_value_pool_words',
                        'bucket_pool_headers','bucket_pools_complete','bucket_pools_unresolved'):
                summary[key]=sum(v.get('summary',{}).get(key,0) for v in views)
            summary['bucket_pool_scans_complete']=sum(
                v.get('summary',{}).get('bucket_pool_scan_complete',0) for v in views)
        summary['metadata_nodes']=max_nodes-remaining_nodes
    result = dict(format='gta6x-psin-schemas-v2', summary=summary,
                scope='Complete recovered PSIN containers only; archive fragments are omitted.',
                interpretation=('LSCH/LENM with bounded inferred values and local field/array/map-entry and ASCII-pool entry associations; unresolved references remain explicit and record-link targets are not expanded.'
                                if with_instances else
                                'LSCH/LENM records with explicitly inferred type meanings; unknown types, fixups and instances remain undecoded.'),
                resources=resources, schemas=rows)
    if with_resource_header:
        result['interpretation'] += ' LRSC header counts and bounded local-record candidates are checked; root-object and fixup meanings remain unknown.'
    if with_record_graph:
        result['interpretation'] += ' Record associations traverse only existing checked local links; candidate reachability is bounded and does not establish a root or complete object graph.'
    if registry is not None:
        result['registry'] = registry.summary()
    return result
