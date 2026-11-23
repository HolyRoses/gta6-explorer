"""Source-checked enum field navigation with explicit interpretation boundaries.

Known enum/bitset storage uses existing native guards. Unknown type0x63 retains
raw width and member-position hypotheses only; no best width or new type is chosen.
"""
from __future__ import annotations

from copy import deepcopy

from . import psin_field_context, psin_instances, psin_schema

PROFILE = 'local_psin_enum_field_evidence_v1'
WIDTHS = (1, 2, 4, 8)
MAX_MEMBERS = 65536
MAX_SNAPSHOT_ITEMS = 2_000_000
MAX_SNAPSHOT_DEPTH = 256
MAX_REPORT_ITEMS = 131072


def inspect(data, schema, instances, queries, *, consume, max_depth=16):
    """Trace <=32 fields to local enum declarations and fresh source evidence.

    A resolved query describes source navigation and a unique local dependency,
    not proof of unknown field semantics. No saved value or registry can supply
    enum authority. Work/output exhaustion returns no report prefix.
    """
    psin_field_context._validate_queries(queries, max_depth, 0)
    if not isinstance(data, bytes) or len(data) > 16*1024*1024:
        raise ValueError('enum context requires bounded source bytes')
    if not isinstance(schema, psin_schema.Schema):
        raise ValueError('enum context requires a local native schema')
    queries = [(bi, ri, list(path)) for bi, ri, path in queries]
    used = 0
    callback_error = None
    def charge(n=1):
        nonlocal used, callback_error
        try:
            consume(n)
        except Exception as exc:
            callback_error = exc
            raise
        used += n
    definitions = schema.enum_table.definitions if schema.enum_table else []
    charge(1+len(schema.structures)+sum(len(o.fields) for o in schema.structures)
           +len(definitions)+sum(len(e.members) for e in definitions))
    local = deepcopy(schema)
    copied, active, memo = 0, set(), {}
    def snapshot(value, depth=0):
        nonlocal copied
        copied += 1
        if copied > MAX_SNAPSHOT_ITEMS or depth > MAX_SNAPSHOT_DEPTH:
            raise ValueError('enum context exceeds snapshot bounds')
        if type(value) in (str, int, float, bool, type(None)):
            if isinstance(value, str) and len(value) > 16*1024*1024:
                raise ValueError('enum context exceeds snapshot string bound')
            return value
        if type(value) not in (dict, list, tuple):
            raise ValueError('enum context requires native JSON-compatible instances')
        identity = id(value)
        if identity in active:
            raise ValueError('enum context instance metadata contains a cycle')
        if identity in memo:
            return memo[identity]
        if len(value) > MAX_SNAPSHOT_ITEMS-copied:
            raise ValueError('enum context exceeds snapshot bounds')
        charge(1+(len(value)+63)//64)
        if len(value) > MAX_SNAPSHOT_ITEMS-copied:
            raise ValueError('enum context exceeds snapshot bounds')
        active.add(identity)
        if isinstance(value, dict):
            entries = tuple(value.items())
            if any(type(k) is not str for k, _ in entries):
                raise ValueError('enum context instance metadata keys must be strings')
            result = {k: snapshot(v, depth+1) for k, v in entries}
        else:
            result = [snapshot(v, depth+1) for v in tuple(value)]
            if isinstance(value, tuple):
                result = tuple(result)
        active.remove(identity); memo[identity] = result
        return result
    private = snapshot(instances)
    contexts = psin_field_context.inspect(data, local, private, queries,
        consume=charge, max_depth=max_depth, max_sample_bytes=0)
    structures = psin_schema._index(local.structures)
    enum_index = psin_schema._index(local.enum_table.definitions if local.enum_table else [])
    owners = {o.section_offset: o for o in local.structures}
    fields_by_offset = {f.section_offset: (o, f) for o in local.structures for f in o.fields}
    charge(len(owners)+len(fields_by_offset)+len(enum_index))
    tables = dict(enums=[], fields=[])
    shared_enums, member_maps, shared_fields = {}, {}, {}
    total_members = report_items = 0
    def emit(value):
        nonlocal report_items
        report_items += 1
        if report_items > MAX_REPORT_ITEMS:
            raise ValueError('enum context exceeds report item bound')
        if isinstance(value, dict):
            charge(1+(len(value)+63)//64)
            return {k: emit(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            charge(1+(len(value)+63)//64)
            return [emit(v) for v in value]
        return value
    def enum_table(definition):
        nonlocal total_members
        key = definition.section_offset
        if key not in shared_enums:
            if len(definition.members) > MAX_MEMBERS-total_members:
                raise ValueError('enum context exceeds local member report limit')
            total_members += len(definition.members)
            charge(1+len(definition.members))
            index = len(tables['enums']); shared_enums[key] = index
            table = definition.as_dict()
            table.update(index=index, source_scope='source-local LENM definition only')
            tables['enums'].append(emit(table))
            values = {}
            for mi, member in enumerate(definition.members):
                values.setdefault(member.value_bits, []).append(mi)
            member_maps[key] = values
        return shared_enums[key]
    output = []
    for proof in contexts['queries']:
        charge()
        q = dict(block_index=proof['block_index'], record_index=proof['record_index'],
            field_path=list(proof['field_path']), status='unresolved',
            logical_type_promoted=False, application_semantics='unknown')
        output.append(q)
        if proof['status'] != 'resolved':
            q['reason'] = proof['reason']; continue
        field = proof['field']; key = (q['block_index'], q['record_index'], tuple(q['field_path']))
        if key in shared_fields:
            previous = shared_fields[key]
            q.update(previous)
            continue
        declaration = fields_by_offset.get(field['declaration_section_offset'])
        if declaration is None:
            raise ValueError('enum context field is absent from private declarations')
        owner, definition = declaration
        if (field['owner_hash'] != f'0x{owner.name_hash:08x}'
                or field['hash'] != f'0x{definition.name_hash:08x}'
                or field['type_word'] != f'0x{definition.type_word:08x}'
                or field['auxiliary'] != f'0x{definition.auxiliary:08x}'):
            raise ValueError('enum context declaration differs from its replayed path')
        code = definition.type_word & 0xffff
        if code not in (0x62, 0x63, 0x65, 0x68) or definition.name_hash == 0x100:
            q['reason'] = 'selected field is outside supported enum-associated declaration scope'
            shared_fields[key] = dict(status=q['status'], reason=q['reason'])
            continue
        candidates = enum_index.get(definition.auxiliary, [])
        evidence = dict(index=len(tables['fields']), source_context=proof,
            field_type_word=f'0x{definition.type_word:08x}', upper_word=definition.type_word>>16,
            upper_word_meaning='unknown' if code == 0x63 else 'existing type profile only',
            local_enum_status='unique' if len(candidates)==1 else 'ambiguous' if candidates else 'missing',
            enum_definition_indices=[enum_table(e) for e in candidates],
            type_meaning='unknown', independently_proven_width=None,
            known_storage=None, width_hypotheses=[], new_type_authorized=False)
        q['field_evidence_index'] = evidence['index']
        if len(candidates) != 1:
            q['reason'] = 'field requires a unique source-local LENM definition'
        else:
            enum = candidates[0]; values = member_maps[enum.section_offset]
            info = psin_schema._type_info(definition, owner, structures, enum_index)
            start = field['source_slot']['data_offset']; slot = field['source_slot']['byte_length']
            if code == 0x63:
                widths = [w for w in WIDTHS if w <= slot and definition.data_offset+w <= owner.byte_size]
                evidence['clear_window_bytes'] = min(slot, 8)
                evidence['clear_window_is_value_width'] = False
                evidence['opaque_window_bits'] = '0x'+data[start:start+min(slot,8)][::-1].hex()
                for width in widths:
                    charge(1+len(values))
                    raw = data[start:start+width]; number = int.from_bytes(raw, 'little')
                    signed = number if not number & (1 << (width*8-1)) else number + (1<<64)-(1<<(width*8))
                    unsigned_matches = list(values.get(number, [])); signed_matches = list(values.get(signed, []))
                    charge(len(unsigned_matches)+len(signed_matches))
                    hypothesis = dict(byte_length=width, raw_bits='0x'+raw[::-1].hex(),
                        unsigned_bits=f'0x{number:016x}', sign_extended_bits=f'0x{signed:016x}',
                        unsigned_member_indices=unsigned_matches, sign_extended_member_indices=signed_matches,
                        all_zero=number==0, independently_authorized=False)
                    if any(position >= width*8 for position in values):
                        mask = dict(status='not_tested', reason='local member values are not bounded positions at this candidate width')
                    else:
                        allowed = sum(1<<position for position in values)
                        set_members = [mi for position, indices in values.items() if number & (1<<position) for mi in indices]
                        charge(len(set_members))
                        mask = dict(status='hypothesis_only', allowed_mask_bits=f'0x{allowed:0{width*2}x}',
                            undefined_bits=f'0x{number & ~allowed:0{width*2}x}',
                            matches_declared_positions=not bool(number & ~allowed),
                            one_hot_numeric=number>0 and number & (number-1)==0,
                            set_member_indices=set_members, meaning_authorized=False)
                    hypothesis['member_position_hypothesis'] = mask
                    evidence['width_hypotheses'].append(hypothesis)
                q.update(status='resolved', resolution_scope='source field/local enum navigation and raw hypotheses only')
            elif info['name'] == 'enum32':
                charge(1+len(values))
                raw = data[start:start+4]; number = int.from_bytes(raw, 'little')
                matches = [mi for bits, indices in values.items() if bits & 0xffffffff == number for mi in indices]
                charge(len(matches))
                evidence.update(type_meaning='existing inferred enum32', known_storage=dict(
                    status='declared_member' if matches else 'undeclared_value', byte_length=4,
                    raw_bits='0x'+raw[::-1].hex(), member_indices=matches,
                    authority='existing enum32 width/slot profile; no new rule'))
                q.update(status='resolved', resolution_scope='source field/local enum navigation and existing profile only')
            elif info['name'] in ('enum_bitset32', 'enum_bitset64'):
                try:
                    decoded = psin_instances._bitset_value(data, start, definition, owner, info,
                        structures, enum_index, local_owner=True, consume=charge, dictionary=None)
                except psin_instances.InstanceLimitError:
                    raise
                except ValueError as exc:
                    if exc is callback_error:
                        raise
                    evidence['known_storage'] = dict(status='unresolved', reason=str(exc),
                        authority='existing bitset guards; refusal preserved')
                    q['reason'] = str(exc)
                else:
                    indices = [mi for bit in decoded['value'] for mi in values[bit]]
                    charge(len(indices))
                    evidence.update(type_meaning='existing inferred '+info['name'], known_storage=dict(
                        status='existing_guard_satisfied', byte_length=decoded['byte_length'],
                        raw_bits=decoded['value_bits'], bit_count=decoded['bit_count'],
                        set_bit_indices=list(decoded['value']), set_member_indices=indices,
                        authority='existing exact-extent bitset profile; no new rule'))
                    q.update(status='resolved', resolution_scope='source field/local enum navigation and existing profile only')
            else:
                q['reason'] = info.get('reason', 'enum-associated storage has no supported existing profile')
        tables['fields'].append(emit(evidence))
        shared_fields[key] = {k:v for k,v in q.items() if k not in ('block_index','record_index','field_path','logical_type_promoted','application_semantics')}
    resolved = sum(q['status']=='resolved' for q in output)
    return dict(format='gta6x-psin-enum-context-v1', profile=PROFILE,
        source_sha256=contexts['source_sha256'], schema_id=contexts['schema_id'], max_depth=max_depth,
        status='complete' if resolved==len(output) else 'partial', queries=output, evidence=tables,
        summary=dict(nodes=used, requested=len(output), resolved=resolved, unresolved=len(output)-resolved,
            fields=len(tables['fields']), enum_definitions=len(tables['enums']), enum_members=total_members,
            unknown63_fields=sum(f['field_type_word'][-4:]=='0063' for f in tables['fields']),
            semantic_types_promoted=0, associations_admitted=0),
        interpretation='Source field/local LENM navigation only. Existing enum/bitset guards remain unchanged; unknown63 literal-width and member-position fits are hypotheses without preferred width, upper-word meaning or new type authority.')
