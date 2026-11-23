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
                    max_nodes: int = 100000, max_depth: int = 16, registry=None,
                    context_records=(), context_fields=(),
                    with_typed_hash_candidates: bool = False, field_trees=(),
                    with_hash_uses: bool = False, hash_words=(), schema_search=None,
                    context_maps=(), with_graph_dot=False, _source_items=None,
                    with_type5c_spans=False, with_type5c_graph=False,
                    with_type5c_diagnostics=False, with_type5c_pool_context=False,
                    context_pools=(), pool_incoming=(), context_enums=()) -> dict:
    """Inspect raw PSIN files or complete joined resources inside archives.

    Identical LSCH+LENM pairs share one schema; differing definitions of the
    same hash remain separate. Sources retain identity and refusal reasons.
    Unrecoverable archive fragments are outside structured.recover's results.
    Instance mode shares one node budget across the report; exhausted or
    unsupported resources keep their verified schemas and explicit refusals.
    """
    from . import structured

    if _source_items is not None and paths:
        raise ValueError('private PSIN buffer sources cannot combine with file paths')
    if with_type5c_graph:
        with_type5c_spans = with_record_graph = True
    if with_graph_dot:
        with_record_graph = True
        if type(max_nodes) is not int or max_nodes < 1:
            raise ValueError('max_nodes must be a positive integer')
    if schema_search is not None:
        allowed = {'structure_hash', 'field_hash', 'type_word', 'auxiliary', 'byte_size', 'same_layout'}
        if (not isinstance(schema_search, dict) or not schema_search or
                any(k not in allowed or type(v) is not int or not 0 <= v <= 0xffffffff
                    for k, v in schema_search.items())):
            raise ValueError('schema search requires supported unsigned 32-bit selectors')
        if type(max_nodes) is not int or max_nodes < 1:
            raise ValueError('max_nodes must be a positive integer')
    if (not isinstance(context_records, (list, tuple)) or len(context_records) > 32 or
            any(not isinstance(pair, (list, tuple)) or len(pair) != 2 or
                any(type(v) is not int or not 0 <= v <= 0xffffffff for v in pair)
                for pair in context_records)):
        raise ValueError('PSIN context queries require at most 32 unsigned block/record pairs')
    if (not isinstance(pool_incoming, (list, tuple)) or len(pool_incoming) > 32 or
            any(not isinstance(pair, (list, tuple)) or len(pair) != 2 or
                any(type(v) is not int or not 0 <= v <= 0xffffffff for v in pair)
                for pair in pool_incoming)):
        raise ValueError('PSIN pool-incoming queries require at most 32 unsigned block/record pairs')
    for label, queries in (('field context', context_fields), ('field trees', field_trees),
                           ('map context', context_maps), ('pool context', context_pools),
                           ('enum context', context_enums)):
        if (not isinstance(queries, (list, tuple)) or len(queries) > 32 or
                any(not isinstance(q, (list, tuple)) or len(q) != 3 or
                    any(type(v) is not int or not 0 <= v <= 0xffffffff for v in q[:2]) or
                    not isinstance(q[2], (list, tuple)) or not 1 <= len(q[2]) <= 64 or
                    any(type(v) is not int or not 0 <= v <= 0xffffffff for v in q[2])
                    for q in queries)):
            raise ValueError('PSIN ' + label + ' requires at most 32 block/record/field-path queries')
    if (not isinstance(hash_words, (list, tuple)) or len(hash_words) > 32 or
            any(type(v) is not int or not 0 <= v <= 0xffffffffffffffff for v in hash_words)):
        raise ValueError('PSIN hash uses require at most 32 unsigned 64-bit words')
    if with_typed_hash_candidates and not isinstance(dictionary, dict):
        raise ValueError('typed hash candidates require an explicit name dictionary')
    with_hash_uses = with_hash_uses or bool(hash_words)
    if with_hash_uses:
        with_typed_hash_candidates = True
    if context_fields or field_trees or context_maps or with_typed_hash_candidates or with_type5c_spans or with_type5c_diagnostics or with_type5c_pool_context or context_pools or pool_incoming or context_enums:
        with_instances = True
        if type(max_nodes) is not int or max_nodes < 1:
            raise ValueError('max_nodes must be a positive integer')
        if type(max_depth) is not int or not 1 <= max_depth <= 64:
            raise ValueError('max_depth must be an integer from 1 to 64')
    if context_records:
        with_record_graph = True
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
    search_schemas = {}
    remaining_nodes = max_nodes
    instance_nodes_used = resource_header_nodes_used = record_graph_nodes_used = 0
    bucket_map_nodes_used = 0
    record_context_nodes_used = 0
    field_view_nodes = dict(field_context=0, field_trees=0, map_context=0, typed_hash_candidates=0, type5c_spans=0,
                            type5c_headers=0, type5c_coverage=0, type5c_targets=0,
                            type5c_scalar_spans=0, type5c_pool_users=0, pool_context=0, pool_incoming=0,
                            enum_context=0)
    if with_resource_header and (type(max_nodes) is not int or max_nodes < 1):
        raise ValueError('max_nodes must be a positive integer')
    if with_instances and (max_nodes < 1 or not 1 <= max_depth <= 64):
        raise ValueError('max_nodes must be positive and max_depth must be 1..64')

    def add(data: bytes, source: dict) -> None:
        nonlocal remaining_nodes, instance_nodes_used, resource_header_nodes_used, record_graph_nodes_used, bucket_map_nodes_used, record_context_nodes_used
        source = dict(source, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
        try:
            schema = parse_schema(data)
        except ValueError as exc:
            resources.append(dict(source, status='refused', error=str(exc)))
            return
        if schema_search is not None:
            search_schemas[schema.schema_id] = schema
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
        def add_field_view(key, inspect):
            nonlocal remaining_nodes
            from . import psin_instances
            if result['instances'].get('status') not in ('complete', 'partial'):
                result[key] = dict(status='refused', reason='field inspection requires available same-source instances')
                return
            before = remaining_nodes
            def consume(amount=1):
                nonlocal remaining_nodes
                if type(amount) is not int or amount < 0:
                    raise ValueError('invalid PSIN field inspection work charge')
                if amount > remaining_nodes:
                    raise psin_instances.InstanceLimitError('PSIN field inspection exceeds shared node budget')
                remaining_nodes -= amount
            try:
                result[key] = inspect(consume)
            except psin_instances.InstanceLimitError as exc:
                remaining_nodes = 0
                result[key] = dict(status='refused', reason=str(exc))
            except ValueError as exc:
                result[key] = dict(status='refused', reason=str(exc))
            field_view_nodes[key] += before - remaining_nodes
        if with_type5c_graph:
            from . import psin_type5c
            add_field_view('type5c_spans', lambda consume: psin_type5c.inspect(
                data, schema, result['instances'], consume=consume, max_depth=max_depth))
        def add_graph(bucket_view=None):
            nonlocal remaining_nodes, record_graph_nodes_used
            from . import psin_record_graph
            before = remaining_nodes
            if result['instances'].get('status') == 'refused':
                result['record_graph'] = dict(status='refused', reason='record graph requires an available instance view')
            elif with_type5c_graph and result['type5c_spans'].get('status') not in ('complete', 'partial'):
                result['record_graph'] = dict(status='refused', reason='type5c graph requires an available checked typed-span view')
            elif with_bucket_graph and (not isinstance(bucket_view, dict) or bucket_view.get('status') not in ('complete', 'partial')):
                result['record_graph'] = dict(status='refused', reason='bucket graph requires an available bucket-map view')
            else:
                try:
                    if with_bucket_graph and bucket_view.get('source_sha256') != source['sha256']:
                        raise ValueError('bucket graph source hash differs from the verified resource')
                    bucket_options = {'bucket_maps': bucket_view} if with_bucket_graph else {}
                    if with_type5c_graph:
                        if result['type5c_spans'].get('source_sha256') != source['sha256']:
                            raise ValueError('type5c graph source hash differs from the verified resource')
                        bucket_options['type5c_spans'] = result['type5c_spans']
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
        if context_records:
            from . import psin_graph_context, psin_record_graph
            if result['record_graph'].get('status') not in ('complete', 'partial'):
                result['record_context'] = dict(status='refused', reason='record context requires an available checked graph')
            else:
                before = remaining_nodes
                def consume_context(amount=1):
                    nonlocal remaining_nodes
                    if type(amount) is not int or amount < 0:
                        raise ValueError('invalid PSIN record-context work charge')
                    if amount > remaining_nodes:
                        raise psin_record_graph.RecordGraphLimitError('PSIN record context exceeds shared node budget')
                    remaining_nodes -= amount
                try:
                    result['record_context'] = psin_graph_context.inspect(
                        result['instances'], result['record_graph'], context_records,
                        consume=consume_context, max_depth=max_depth,
                        resource_header=result.get('resource_header'),
                        bucket_maps=result.get('bucket_maps') if with_bucket_graph else None,
                        **({'type5c_spans': result['type5c_spans']} if with_type5c_graph else {}))
                except psin_record_graph.RecordGraphLimitError as exc:
                    remaining_nodes = 0
                    result['record_context'] = dict(status='refused', reason=str(exc))
                except ValueError as exc:
                    result['record_context'] = dict(status='refused', reason=str(exc))
                record_context_nodes_used += before - remaining_nodes
        if context_fields:
            from . import psin_field_context
            add_field_view('field_context', lambda consume: psin_field_context.inspect(
                data, schema, result['instances'], context_fields,
                consume=consume, max_depth=max_depth))
        if field_trees:
            from . import psin_field_tree
            add_field_view('field_trees', lambda consume: psin_field_tree.inspect(
                data, schema, result['instances'], field_trees,
                consume=consume, max_depth=max_depth))
        if context_maps:
            from . import psin_map_context
            add_field_view('map_context', lambda consume: psin_map_context.inspect(
                data, schema, result['instances'], context_maps,
                consume=consume, max_depth=max_depth))
        if with_type5c_spans and not with_type5c_graph:
            from . import psin_type5c
            add_field_view('type5c_spans', lambda consume: psin_type5c.inspect(
                data, schema, result['instances'], consume=consume, max_depth=max_depth))
        if with_type5c_diagnostics:
            from . import psin_type5c_headers, psin_type5c_coverage, psin_type5c_targets
            for key, inspect in (('type5c_headers', psin_type5c_headers.inspect),
                                 ('type5c_coverage', psin_type5c_coverage.inspect),
                                 ('type5c_targets', psin_type5c_targets.inspect)):
                add_field_view(key, lambda consume, inspect=inspect: inspect(
                    data, schema, result['instances'], consume=consume, max_depth=max_depth))
        if with_type5c_pool_context:
            from . import psin_type5c_scalars, psin_type5c_pool_users
            for key, inspect in (('type5c_scalar_spans', psin_type5c_scalars.inspect),
                                 ('type5c_pool_users', psin_type5c_pool_users.inspect)):
                add_field_view(key, lambda consume, inspect=inspect: inspect(
                    data, schema, result['instances'], consume=consume, max_depth=max_depth))
        if context_pools:
            from . import psin_pool_context
            add_field_view('pool_context', lambda consume: psin_pool_context.inspect(
                data, schema, result['instances'], context_pools, consume=consume, max_depth=max_depth))
        if pool_incoming:
            from . import psin_pool_incoming
            add_field_view('pool_incoming', lambda consume: psin_pool_incoming.inspect(
                data, schema, result['instances'], pool_incoming, consume=consume, max_depth=max_depth))
        if context_enums:
            from . import psin_enum_context
            add_field_view('enum_context', lambda consume: psin_enum_context.inspect(
                data, schema, result['instances'], context_enums, consume=consume, max_depth=max_depth))
        if with_typed_hash_candidates:
            from . import world_asset_types
            add_field_view('typed_hash_candidates', lambda consume: world_asset_types.inspect(
                data, schema, result['instances'], dictionary if dictionary is not None else {},
                consume=consume, max_depth=max_depth))
        resources.append(result)

    source_items = iter_sources(paths, limit=limit) if _source_items is None else _source_items
    for source, data, error in source_items:
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
        if with_type5c_graph:
            for key in ('type5c_headers_supported', 'type5c_headers_unresolved',
                        'type5c_record_edges', 'type5c_inline_headers_excluded',
                        'type5c_inline_links_excluded', 'type5c_scan_partial'):
                summary['record_graph_' + key] = sum(g.get('summary', {}).get(key, 0) for g in graphs)
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
    if context_records:
        views = [r['record_context'] for r in resources if 'record_context' in r]
        summary['record_context_nodes'] = record_context_nodes_used
        summary['record_context_resources_refused'] = sum(v['status'] == 'refused' for v in views)
        for key in ('queries', 'resolved', 'unresolved'):
            summary['record_context_' + key] = sum(v.get('summary', {}).get(key, 0) for v in views)
        summary['metadata_nodes'] = max_nodes - remaining_nodes
    for enabled, key, counters in (
            (bool(context_fields), 'field_context', ('queries', 'resolved', 'unresolved', 'opaque_prefix_bytes')),
            (bool(field_trees), 'field_trees', ('requested_trees', 'trees_complete', 'trees_partial', 'fields', 'resolved', 'unresolved', 'opaque_prefix_bytes')),
            (bool(context_maps), 'map_context', ('requested', 'resolved', 'unresolved', 'map_entries')),
            (with_type5c_spans, 'type5c_spans', ('headers', 'fields_complete', 'fields_unresolved', 'targets_complete', 'record_links')),
            (with_type5c_diagnostics, 'type5c_headers', ()),
            (with_type5c_diagnostics, 'type5c_coverage', ()),
            (with_type5c_diagnostics, 'type5c_targets', ()),
            (with_type5c_pool_context, 'type5c_scalar_spans', ()),
            (with_type5c_pool_context, 'type5c_pool_users', ()),
            (bool(context_pools), 'pool_context', ('requested', 'resolved', 'unresolved')),
            (bool(pool_incoming), 'pool_incoming', ('requested', 'resolved', 'unresolved')),
            (bool(context_enums), 'enum_context', ('requested', 'resolved', 'unresolved')),
            (with_typed_hash_candidates, 'typed_hash_candidates',
             ('selected_slots', 'matched_slots', 'unmatched_slots', 'unsupported_slots', 'asset_bindings'))):
        if enabled:
            views = [r[key] for r in resources if key in r]
            summary[key + '_nodes'] = field_view_nodes[key]
            summary[key + '_resources_refused'] = sum(v['status'] == 'refused' for v in views)
            for counter in counters:
                summary[key + '_' + counter] = sum(v.get('summary', {}).get('requested' if key == 'field_context' and counter == 'queries' else counter, 0) for v in views)
            summary['metadata_nodes'] = max_nodes - remaining_nodes
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
    if with_hash_uses:
        from . import psin_hash_uses, psin_instances
        before = remaining_nodes
        def consume_hash_uses(amount=1):
            nonlocal remaining_nodes
            if type(amount) is not int or amount < 0:
                raise ValueError('invalid PSIN hash-use work charge')
            if amount > remaining_nodes:
                raise psin_instances.InstanceLimitError('PSIN hash uses exceed shared node budget')
            remaining_nodes -= amount
        try:
            result['hash_uses'] = psin_hash_uses.inspect(resources, consume=consume_hash_uses, words=hash_words)
        except psin_instances.InstanceLimitError as exc:
            remaining_nodes = 0
            result['hash_uses'] = dict(status='refused', reason=str(exc))
        except ValueError as exc:
            result['hash_uses'] = dict(status='refused', reason=str(exc))
        summary['hash_uses_nodes'] = before - remaining_nodes
        summary['hash_uses_refused'] = int(result['hash_uses']['status'] == 'refused')
        summary['metadata_nodes'] = max_nodes - remaining_nodes
    if schema_search is not None:
        from . import psin_schema_search, psin_instances
        before = remaining_nodes
        def consume_search(amount=1):
            nonlocal remaining_nodes
            if type(amount) is not int or amount < 0:
                raise ValueError('invalid PSIN schema-search work charge')
            if amount > remaining_nodes:
                raise psin_instances.InstanceLimitError('PSIN schema search exceeds shared node budget')
            remaining_nodes -= amount
        try:
            result['schema_search'] = psin_schema_search.inspect(
                search_schemas, resources, consume=consume_search, **schema_search)
        except psin_instances.InstanceLimitError as exc:
            remaining_nodes = 0
            result['schema_search'] = dict(status='refused', reason=str(exc))
        except ValueError as exc:
            result['schema_search'] = dict(status='refused', reason=str(exc))
        summary['schema_search_nodes'] = before - remaining_nodes
        summary['schema_search_refused'] = int(result['schema_search']['status'] == 'refused')
        summary['metadata_nodes'] = max_nodes - remaining_nodes
    if with_graph_dot:
        from . import psin_graph_dot, psin_instances
        before = remaining_nodes
        def consume_dot(amount=1):
            nonlocal remaining_nodes
            if type(amount) is not int or amount < 0:
                raise ValueError('invalid PSIN graph-DOT work charge')
            if amount > remaining_nodes:
                raise psin_instances.InstanceLimitError('PSIN graph DOT exceeds shared node budget')
            remaining_nodes -= amount
        try:
            result['graph_dot'] = psin_graph_dot.inspect(resources, consume=consume_dot)
        except psin_instances.InstanceLimitError as exc:
            remaining_nodes = 0
            result['graph_dot'] = dict(status='refused', reason=str(exc))
        except ValueError as exc:
            result['graph_dot'] = dict(status='refused', reason=str(exc))
        summary['graph_dot_nodes'] = before - remaining_nodes
        summary['graph_dot_refused'] = int(result['graph_dot']['status'] == 'refused')
        summary['metadata_nodes'] = max_nodes - remaining_nodes
    if registry is not None:
        result['registry'] = registry.summary()
    return result
