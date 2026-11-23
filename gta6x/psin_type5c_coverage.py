"""Explain checked type5c target coverage without admitting additional links.

Observed row coverage is geometric evidence only. Uncovered bytes are never
classified as padding, sentinels, empty objects or application-owned storage.
"""
from __future__ import annotations

from . import psin_type5c

PROFILE = 'local_type5c_target_coverage_explanation_v1'
MAX_ROWS = 4096


def inspect(data, schema, instances, *, consume, max_depth=16):
    """Recompute fresh span evidence and explain bounded gaps/overlaps.

    The existing reader supplies independently declared target spans. Its
    eligibility, complete-scan requirement and refusal decisions are unchanged.
    All rows are existing native instance identities, never new associations.
    Saved reports are not accepted as source authority. Failure returns no prefix.
    """
    used = 0
    def charge(amount=1):
        nonlocal used
        consume(amount)
        used += amount
    original = psin_type5c.inspect(data, schema, instances, consume=charge, max_depth=max_depth)
    charge(2 + len(original['fields']) + len(original['targets']))
    groups = {}
    for field in original['fields']:
        target = field.get('target')
        if target is not None:
            groups.setdefault(target['block_index'], []).append(field)
    targets = []
    row_total = span_total = alias_total = gap_bytes = overlap_bytes = uncovered_rows = 0
    for candidate in original['targets']:
        bi = candidate['block_index']
        fields = groups[bi]
        stride = candidate['declared_record_stride']
        count = candidate['byte_length'] // stride
        if count > MAX_ROWS - row_total:
            raise ValueError('type5c coverage exceeds the 4096-existing-row report limit')
        row_total += count
        charge(1 + count)
        block = instances['blocks'][bi]
        records = block.get('records')
        if (type(block.get('record_count')) is not int or block['record_count'] != count
                or not isinstance(records, list) or len(records) != count):
            raise ValueError('type5c coverage target row count differs from its local stride')
        for ri, record in enumerate(records):
            expected = dict(structure_hash=candidate['structure_hash'],
                data_offset=candidate['data_offset'] + ri * stride, byte_length=stride)
            if not isinstance(record, dict) or any(record.get(k) != v for k, v in expected.items()):
                raise ValueError('type5c coverage target row identity differs from its source span')
        spans = {}
        for field in fields:
            charge()
            target = field['target']
            key = target['byte_offset'], target['byte_length']
            spans.setdefault(key, []).append(field)
        changes = [0] * (count + 1)
        header_changes = [0] * (count + 1)
        span_rows = []
        for (offset, length), witnesses in sorted(spans.items()):
            charge(1 + len(witnesses))
            first, past = offset // stride, (offset + length) // stride
            changes[first] += 1; changes[past] -= 1
            header_changes[first] += len(witnesses); header_changes[past] -= len(witnesses)
            span_rows.append(dict(byte_offset=offset, data_offset=candidate['data_offset'] + offset,
                byte_length=length, first_record_index=first, record_count=past-first,
                headers=[dict(header_index=f['index'], field_index=f['field_index'], header_data_offset=f['header_data_offset'],
                    owner_hash=f['owner_hash'], field_hash=f['field_hash'],
                    legacy_status=f['status'], legacy_reason=f.get('reason')) for f in witnesses]))
        rows = []
        gaps, overlaps = [], []
        distinct = headers = 0
        for ri in range(count):
            charge()
            distinct += changes[ri]; headers += header_changes[ri]
            at = candidate['data_offset'] + ri * stride
            rows.append(dict(block_index=bi, record_index=ri,
                structure_hash=candidate['structure_hash'], data_offset=at, byte_length=stride,
                observed_distinct_span_count=distinct, observed_header_count=headers,
                association_admitted=False))
            segments = gaps if distinct == 0 else overlaps if distinct > 1 else None
            if segments is not None:
                if segments and segments[-1]['first_record_index'] + segments[-1]['record_count'] == ri:
                    segments[-1]['record_count'] += 1
                    segments[-1]['byte_length'] += stride
                else:
                    charge()
                    segments.append(dict(byte_offset=ri*stride, data_offset=at, byte_length=stride,
                        first_record_index=ri, record_count=1))
        local_gaps = sum(s['byte_length'] for s in gaps)
        local_overlap = sum(s['byte_length'] for s in overlaps)
        local_uncovered = sum(s['record_count'] for s in gaps)
        aliases = len(fields) - len(spans)
        gap_bytes += local_gaps; overlap_bytes += local_overlap; uncovered_rows += local_uncovered
        span_total += len(spans); alias_total += aliases
        targets.append(dict(block_index=bi, structure_hash=candidate['structure_hash'],
            data_offset=candidate['data_offset'], byte_length=candidate['byte_length'],
            declared_record_stride=stride, record_count=count,
            observed_coverage='whole_target' if not gaps and not overlaps else 'gaps_and_overlaps'
                if gaps and overlaps else 'gaps' if gaps else 'overlaps',
            scan_complete=original['scan_complete'], legacy_status=candidate['status'],
            legacy_reason=candidate.get('reason'), spans=span_rows, exact_alias_headers=aliases,
            gaps=gaps, overlaps=overlaps, existing_rows=rows,
            uncovered_bytes=local_gaps, multiply_covered_bytes=local_overlap,
            semantic_owner='unknown', uncovered_content_meaning='unknown', associations_admitted=0))
    return dict(format='gta6x-psin-type5c-coverage-v1', profile=PROFILE,
        source_sha256=original['source_sha256'], schema_id=original['schema_id'], max_depth=max_depth,
        status=original['status'], scan_complete=original['scan_complete'],
        scan_reasons=list(original['scan_reasons']), targets=targets,
        summary=dict(nodes=used, targets=len(targets), rows=row_total, distinct_spans=span_total,
            exact_alias_headers=alias_total, targets_with_gaps=sum(bool(t['gaps']) for t in targets),
            targets_with_overlaps=sum(bool(t['overlaps']) for t in targets),
            uncovered_bytes=gap_bytes, multiply_covered_bytes=overlap_bytes, uncovered_rows=uncovered_rows,
            legacy_record_links=original['summary']['record_links'],
            headers_without_target=sum('target' not in f for f in original['fields']),
            associations_admitted=0, semantic_types_promoted=0),
        interpretation='Observed geometric coverage of independently declared local typed rows. Existing eligible-scan and whole-target refusals remain unchanged; no new record links, primitive values, padding, sentinel, logical element or ownership meanings are inferred.')
