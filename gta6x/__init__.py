"""gta6x — read-only explorer for GTA VI packages.

Parses the RPF9 container headers, describes the `RDS5` streaming resources,
and carves the plaintext media carriers (Bink2 video, AWC audio) that the
archives store without encryption.

Deliberately dependency-free: standard library only.
"""

__version__ = "1.0.0"
__all__ = ["bc", "rpf", "rds5", "gfx10", "texture", "psin", "media", "shaders",
           "structured", "embedded", "models", "world", "names", "anim",
           "inventory", "report", "cli", "tui"]

# Preserve existing imports while implementations live together in gta6x.bc.
from .bc._compat import install_legacy_aliases as _install_bc_aliases
_install_bc_aliases()
del _install_bc_aliases
