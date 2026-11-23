"""Public serialized SFI0 feature declarations; unknown bits stay lossless.

These are container feature-bit positions, not the DXIL module flag namespace.
Stored declarations do not verify executable use, hardware support or game assets.
"""
from __future__ import annotations

import struct

# Public SFI0 enum facts, with local presentation labels.
_FEATURES = {
    0: 'double_precision', 1: 'compute_raw_structured_buffers',
    2: 'uav_all_stages', 3: 'uav_64_slots', 4: 'minimum_precision',
    5: 'double_extensions_11_1', 6: 'shader_extensions_11_1',
    7: 'comparison_filtering_level9', 8: 'tiled_resources',
    9: 'stencil_reference', 10: 'inner_coverage', 11: 'typed_uav_load_formats',
    12: 'raster_ordered_views', 13: 'viewport_render_target_index',
    14: 'wave_operations', 15: 'integer_64_operations', 16: 'view_id',
    17: 'barycentrics', 18: 'native_low_precision', 19: 'shading_rate',
    20: 'raytracing_tier_1_1', 21: 'sampler_feedback',
    22: 'atomic_64_typed_resource', 23: 'atomic_64_group_shared',
    24: 'derivatives_mesh_amplification', 25: 'resource_heap_indexing',
    26: 'sampler_heap_indexing', 28: 'atomic_64_heap_resource',
    29: 'advanced_texture_operations', 30: 'writable_msaa_textures',
    31: 'sample_compare_gradient_bias', 32: 'extended_command_information',
}


def inspect(body: bytes, origin: int, spend) -> dict:
    """Read exactly one public 64-bit little-endian feature word."""
    if len(body) != 8:
        raise ValueError('SFI0 feature flags require exactly eight bytes')
    value = struct.unpack('<Q', body)[0]
    spend(value.bit_count())
    flags = []
    known = 0
    for index in range(64):
        bit = 1 << index
        if not value & bit:
            continue
        name = _FEATURES.get(index)
        if name is not None:
            known |= bit
        flags.append(dict(bit_index=index, mask_bits=f'0x{bit:016x}', name=name,
            status='known' if name is not None else 'reserved' if index == 27 else 'unknown'))
    return dict(status='complete', tag='SFI0', data_offset=origin, byte_length=8,
        flags_bits=f'0x{value:016x}', known_bits=f'0x{known:016x}',
        unknown_bits=f'0x{value & ~known:016x}',
        reserved_bits=f'0x{value & (1 << 27):016x}', set_bit_count=len(flags), flags=flags,
        scope='stored public SFI0 declarations only; executable use, hardware compatibility and game identities unverified')
