"""Bounded LRSC resource-header counts and a local-record candidate.

The measured header repeats independently parsed schema/enum/block counts.
Its block selector fits one local typed record. This is a candidate association,
not a proven root object, fixup list or instruction to traverse unknown data.
"""
from __future__ import annotations

import struct

from . import psin, psin_schema
from .psin_blocks import parse_blocks

PROFILE = 'lrsc_header_counts_local_record_candidate_v1'
MAX_BYTES = 16 * 1024 * 1024
NODES = 6


class ResourceHeaderLimitError(ValueError):
    """The requested resource-header view exceeds its explicit node budget."""


def inspect(data: bytes, *, max_nodes: int = 100000) -> dict:
    """Cross-check the exact observed LRSC header, without decoding targets.

    Malformed containers, checksums and schema/block framing raise ValueError.
    Unsupported LRSC profiles retain a reason and no candidate/header prefix.
    No registry or external schema can authorize this local association.
    """
    if type(max_nodes) is not int or max_nodes < 1:
        raise ResourceHeaderLimitError('PSIN resource-header output exceeds node limit')
    if len(data) > MAX_BYTES:
        raise ValueError('PSIN resource-header input exceeds resource size limit')
    container = psin.parse_container(data)
    if container is None or not container.checksum_verified:
        raise ValueError('resource-header reader requires a complete checksum-verified PSIN container')
    schema = psin_schema.parse_schema(data)
    body = container.section('PSIN')
    blocks = parse_blocks(data[:body.length])
    section = container.section('LRSC')
    result = dict(format='gta6x-psin-resource-header-v1', status='unresolved',
                  interpretation='candidate; LRSC fixups and root-object semantics remain unknown',
                  candidate_profile=PROFILE, summary=dict(nodes=1, record_candidates=0))
    def refuse(reason):
        return dict(result, reason=reason)

    raw = data[section.offset + 8:section.offset + section.length]
    if len(raw) != 80:
        return refuse('unsupported LRSC resource-header extent; requires 80 payload bytes')
    if raw[:4] != b'0DRP' or struct.unpack_from('<I', raw, 4)[0] != 122:
        return refuse('unsupported LRSC resource-header magic or version')
    if raw[8:16] != bytes(8) or raw[72:80] != bytes(8):
        return refuse('unsupported LRSC resource-header zero-word profile')
    if raw[24:56] != b'\xbb' * 32 or raw[64:72] != b'\xbb' * 8:
        return refuse('unsupported LRSC resource-header sentinel profile')
    ns, ne, nb, unknown = struct.unpack_from('<4H', raw, 56)
    if unknown or (ns, ne, nb) != (len(schema.structures), len(schema.enum_table.definitions), len(blocks)):
        return refuse('LRSC counts do not match local LSCH/LENM/PSIN tables')
    word = struct.unpack_from('<Q', raw, 16)[0]
    # Discovery establishes exact one-based block numbers, not general offsets.
    if not 1 <= word <= len(blocks):
        return refuse('unsupported LRSC full-word block selector')
    block = blocks[word - 1]
    definitions = [s for s in schema.structures if s.name_hash == block.type_hash]
    if len(definitions) != 1 or definitions[0].byte_size <= 0:
        return refuse('LRSC candidate lacks a unique positive-sized local structure')
    definition = definitions[0]
    if block.byte_length != definition.byte_size:
        return refuse('LRSC candidate block is not exactly one local typed record')
    if max_nodes < NODES:
        raise ResourceHeaderLimitError('PSIN resource-header output exceeds node limit')
    result.update(status='complete', interpretation='inferred header/count consistency; record association is a candidate, not a proven root',
                  profile=result.pop('candidate_profile'),
                  section=dict(data_offset=section.offset, byte_length=section.length,
                               payload_data_offset=section.offset + 8, payload_byte_length=80),
                  header=dict(magic='0DRP', version=122,
                              value_bits='0x' + raw[::-1].hex(),
                              selector_data_offset=section.offset + 24,
                              selector_bits=f'0x{word:016x}'),
                  counts=dict(structures=ns, enums=ne, blocks=nb),
                  record_candidate=dict(status='candidate', block_index=block.index,
                      record_index=0, data_offset=block.data_offset,
                      byte_length=block.byte_length, structure_hash=f'0x{block.type_hash:08x}',
                      schema_definition_offset=definition.section_offset,
                      interpretation='one bounded local typed record; role unconfirmed'),
                  summary=dict(nodes=NODES, record_candidates=1, structures=ns, enums=ne, blocks=nb))
    return result
