"""Keep historical gta6x.bc* imports mapped to the canonical package modules.

Aliases share module objects, caches and warning classes. There are no duplicate
implementations or data copies. New callers should import from gta6x.bc.
"""
from importlib import import_module
import sys


def install_legacy_aliases():
    parent_name = __package__.rsplit('.', 1)[0]
    parent = sys.modules[parent_name]
    aliases = {
        'bcn': 'bcn',
        'bc6h': 'bc6h',
        'bc6h_tables': 'tables.bc6h',
        'bc7': 'bc7',
        'bc7_tables': 'tables.bc7',
        'bcpack': 'bcpack.decoder',
        'bcpack_bc345': 'bcpack.blocks',
        'bcpack_spec': 'bcpack.spec',
        'bcpack_tables': 'bcpack.tables',
        'bcpack_data': 'bcpack.data',
    }
    for old, new in aliases.items():
        module = import_module(f'{__package__}.{new}')
        sys.modules[f'{parent_name}.{old}'] = module
        setattr(parent, old, module)
