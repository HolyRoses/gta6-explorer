"""Signature-aware cross-file PSIN definitions from user-supplied metadata.

Built from checksum-verified containers, or reloaded structurally checked
LSCH/LENM sections. Conflicting versions are retained, never voted or guessed.
No GPL implementation or external schema/type table is used.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
import struct
import tempfile

from . import psin_schema

MAX_SECTION_BYTES = 16 * 1024 * 1024
MAX_REGISTRY_BYTES = 64 * 1024 * 1024
MAX_FILE_BYTES = 160 * 1024 * 1024
MAX_SCHEMAS = 65536
MAX_SOURCES = 100000

__all__ = ['Registry', 'Scope', 'Resolution', 'definition_id']


def definition_id(kind, definition):
    """Full-content identity, excluding section-relative locations only."""
    if kind == 'structure':
        d = definition
        raw = struct.pack('<6IH', d.name_hash, d.unknown_04, d.unknown_08,
                          d.unknown_0c, d.byte_size, len(d.fields), d.unknown_1c)
        raw += b''.join(struct.pack('<4I', f.name_hash, f.data_offset, f.type_word, f.auxiliary)
                        for f in d.fields)
    elif kind == 'enum':
        d = definition
        raw = struct.pack('<4I', d.name_hash, d.unknown_04, d.unknown_14, len(d.members))
        raw += b''.join(struct.pack('<QII', m.value_bits, m.name_hash, m.unknown_0c)
                        for m in d.members)
    else:
        raise ValueError('unknown PSIN definition kind')
    return hashlib.sha256(kind.encode('ascii') + b'\0' + raw).hexdigest()


@dataclass
class Variant:
    id: str
    signature: int
    definition: object
    schema_ids: set[str] = field(default_factory=set)


@dataclass
class Resolution:
    status: str
    scope: str
    variants: list[Variant]

    @property
    def definition(self):
        return self.variants[0].definition if self.status == 'resolved' else None

    def as_dict(self):
        return dict(status=self.status, scope=self.scope, candidate_count=len(self.variants),
                    candidates=[dict(id=v.id, signature=f'0x{v.signature:08x}')
                                for v in sorted(self.variants, key=lambda x: x.id)[:8]],
                    candidate_list_truncated=len(self.variants) > 8)


class Registry:
    def __init__(self):
        self.schemas = {}
        self.sections = {}
        self.sources = {}
        self.variants = {'structure': {}, 'enum': {}}
        self.section_bytes = 0
        self.source_count = 0
        self.verification = 'checksum_verified_inputs'
        self.generation = 0

    def _add_schema(self, schema, ls, en, source):
        ident = schema.schema_id
        if source not in self.sources.get(ident, []) and self.source_count >= MAX_SOURCES:
            raise ValueError('PSIN registry source budget exceeded')
        if ident not in self.schemas:
            if len(self.schemas) >= MAX_SCHEMAS or self.section_bytes + len(ls) + len(en) > MAX_REGISTRY_BYTES:
                raise ValueError('PSIN registry section budget exceeded')
            self.schemas[ident] = schema
            self.sections[ident] = ls, en
            self.sources[ident] = []
            self.section_bytes += len(ls) + len(en)
            self.generation += 1
            for kind, definitions in (('structure', schema.structures),
                                      ('enum', schema.enum_table.definitions)):
                for definition in definitions:
                    bucket = self.variants[kind].setdefault(definition.name_hash, {})
                    key = definition_id(kind, definition)
                    if key not in bucket:
                        bucket[key] = Variant(key, definition.unknown_04, definition)
                    bucket[key].schema_ids.add(ident)
        if source not in self.sources[ident]:
            self.sources[ident].append(dict(source))
            self.source_count += 1
        return ident

    def add(self, data: bytes, source: dict | None = None):
        """Add definitions from one complete checksum-verified PSIN container."""
        from . import psin
        if len(data) > MAX_SECTION_BYTES:
            raise ValueError('PSIN registry input exceeds resource size limit')
        schema = psin_schema.parse_schema(data)
        parsed = psin.parse_container(data)
        ls, en = parsed.section('LSCH'), parsed.section('LENM')
        if source is not None and not isinstance(source, dict):
            raise ValueError('invalid PSIN registry source metadata')
        location = source or {}
        try:
            label = os.path.basename(os.fspath(location.get('file', '<memory>')))
        except TypeError:
            raise ValueError('invalid PSIN registry source filename') from None
        metadata = dict(file=label,
                        offset=location.get('offset', 0), sha256=hashlib.sha256(data).hexdigest())
        self._validate_source(metadata)
        return self._add_schema(schema, data[ls.offset:ls.offset+ls.length],
                                data[en.offset:en.offset+en.length], metadata)

    @staticmethod
    def _validate_source(source):
        if (not isinstance(source, dict) or set(source) != {'file','offset','sha256'}
                or not isinstance(source['file'], str) or len(source['file']) > 256
                or os.path.basename(source['file']) != source['file']
                or type(source['offset']) is not int or not 0 <= source['offset'] < (1 << 64)
                or not isinstance(source['sha256'], str) or len(source['sha256']) != 64):
            raise ValueError('invalid PSIN registry source metadata')
        try:
            if len(bytes.fromhex(source['sha256'])) != 32:
                raise ValueError
        except ValueError:
            raise ValueError('invalid PSIN registry source hash') from None

    def resolve(self, kind, name_hash, signature=None):
        if kind not in self.variants:
            raise ValueError('unknown PSIN definition kind')
        if (type(name_hash) is not int or not 0 <= name_hash < (1 << 32)
                or (signature is not None and
                    (type(signature) is not int or not 0 <= signature < (1 << 32)))):
            raise ValueError('PSIN registry names and signatures must be uint32')
        variants = list(self.variants[kind].get(name_hash, {}).values())
        if signature is not None:
            variants = [v for v in variants if v.signature == signature]
        # Conservative file-local policy, not an assertion that these are all
        # synthetic format ids. A plausible size never overrides this rule.
        if name_hash < 0x10000:
            return Resolution('reserved', 'registry', variants)
        if not variants:
            return Resolution('missing', 'registry', [])
        if len(variants) > 1:
            status = 'signature_conflict' if len({v.signature for v in variants}) == 1 else 'ambiguous'
            return Resolution(status, 'registry', variants)
        return Resolution('resolved', 'registry', variants)

    def scope(self, schema):
        return Scope(schema, self)

    def build(self, paths, *, limit):
        """Add recovered containers, retaining explicit per-input refusals."""
        report = dict(inputs=0, accepted=0, refused=[])
        for source, data, error in psin_schema.iter_sources(paths, limit=limit):
            report['inputs'] += 1
            if error is None:
                try:
                    self.add(data, source)
                    report['accepted'] += 1
                except ValueError as exc:
                    error = str(exc)
            if error is not None:
                report['refused'].append(dict(source, error=error))
        return report

    def summary(self):
        result = dict(schema_pairs=len(self.schemas), sources=self.source_count,
                      section_bytes=self.section_bytes, verification=self.verification)
        for kind, buckets in self.variants.items():
            result[kind+'_names'] = len(buckets)
            result[kind+'_variants'] = sum(len(v) for v in buckets.values())
            result[kind+'_resolvable_names'] = sum(key >= 0x10000 and len(v) == 1
                                                   for key,v in buckets.items())
            result[kind+'_conflicting_names'] = sum(len(v) > 1 for v in buckets.values())
            result[kind+'_signature_conflicts'] = sum(
                len(group) > len({v.signature for v in group.values()})
                for group in buckets.values())
        return result

    def as_dict(self):
        return dict(format='gta6x-psin-registry-v1', schemas=[
            dict(id=key, lsch_hex=self.sections[key][0].hex(), lenm_hex=self.sections[key][1].hex(),
                 sources=sorted(self.sources[key], key=lambda s:(s['file'],s['offset'],s['sha256'])))
            for key in sorted(self.schemas)])

    @classmethod
    def from_dict(cls, obj):
        """Validate sections and identities; source checksums cannot be reverified."""
        if (not isinstance(obj, dict) or set(obj) != {'format', 'schemas'}
                or obj.get('format') != 'gta6x-psin-registry-v1'):
            raise ValueError('unsupported PSIN registry format')
        entries = obj.get('schemas')
        if not isinstance(entries, list) or len(entries) > MAX_SCHEMAS:
            raise ValueError('invalid PSIN registry schema list')
        registry = cls()
        registry.verification = 'sections_validated; source_checksums_not_reverified'
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {'id', 'lsch_hex', 'lenm_hex', 'sources'}:
                raise ValueError('invalid PSIN registry schema entry')
            ls, en = entry.get('lsch_hex'), entry.get('lenm_hex')
            if (not isinstance(ls, str) or not isinstance(en, str) or
                    len(ls) + len(en) > MAX_SECTION_BYTES * 2):
                raise ValueError('invalid PSIN registry section size')
            try:
                ls, en = bytes.fromhex(ls), bytes.fromhex(en)
            except ValueError:
                raise ValueError('invalid PSIN registry section hex') from None
            schema = psin_schema.parse_lsch(ls)
            schema.enum_table = psin_schema.parse_lenm(en)
            if schema.schema_id != entry.get('id') or schema.schema_id in registry.schemas:
                raise ValueError('PSIN registry schema identity mismatch or duplicate')
            sources = entry.get('sources')
            if not isinstance(sources, list) or not sources or len(sources) > MAX_SOURCES:
                raise ValueError('invalid PSIN registry source list')
            for source in sources:
                cls._validate_source(source)
            for source in sources:
                registry._add_schema(schema, ls, en, source)
        return registry

    @classmethod
    def load(cls, path):
        with open(path, 'rb') as handle:
            data = handle.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise ValueError('PSIN registry file size limit exceeded')
        return cls.from_dict(json.loads(data))

    def save(self, path):
        # Caller checks output/input collisions, as for schema JSON exports.
        fd, temporary = tempfile.mkstemp(prefix='.psin-registry-', dir=os.path.dirname(os.path.abspath(path)))
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(self.as_dict(), handle, separators=(',',':'))
                handle.write('\n')
                if handle.tell() > MAX_FILE_BYTES:
                    raise ValueError('PSIN registry file size limit exceeded')
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


class DefinitionIndex:
    def __init__(self, scope, kind):
        self.scope, self.kind = scope, kind

    def get(self, name_hash, default=None):
        resolution = self.scope.resolve(self.kind, name_hash)
        # Retain local duplicates as ambiguity; never deduplicate them away.
        if resolution.scope == 'local':
            return self.scope.local[self.kind].get(name_hash, default)
        return [resolution.definition] if resolution.definition is not None else (default if default is not None else [])

    def resolution(self, name_hash):
        return self.scope.resolve(self.kind, name_hash).as_dict()


class Scope:
    """Local authority plus global fallback; foreign members use global scope.

    Imported definitions never inherit the recipient's local namespace or an
    arbitrarily selected donor file's dependencies. Global ambiguity stays so.
    """
    def __init__(self, schema, registry=None):
        self.schema, self.registry = schema, registry
        self.local = {'structure': psin_schema._index(schema.structures) if schema else {},
                      'enum': psin_schema._index(schema.enum_table.definitions)
                      if schema and schema.enum_table else {}}
        self.structures = DefinitionIndex(self, 'structure')
        self.enums = DefinitionIndex(self, 'enum')
        self._global = None
        self._cache = {}

    def resolve(self, kind, name_hash):
        key = kind, name_hash, self.registry.generation if self.registry else 0
        if key in self._cache:
            return self._cache[key]
        definitions = self.local[kind].get(name_hash)
        if definitions:
            variants = [Variant(definition_id(kind,d),d.unknown_04,d) for d in definitions]
            result = Resolution('resolved' if len(variants) == 1 else 'ambiguous', 'local', variants)
        else:
            result = self.registry.resolve(kind,name_hash) if self.registry else Resolution('missing','local',[])
        self._cache[key] = result
        return result

    def child_scope(self, name_hash):
        if self.schema is None:
            return self
        if name_hash in self.local['structure']:
            return self
        if self._global is None:
            self._global = Scope(None, self.registry)
        return self._global
