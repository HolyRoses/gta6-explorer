"""gta6x — read-only explorer for the GTA VI Xbox 1.0.2.1 package.

Parses the RPF9 container headers, describes the `RDS5` streaming resources,
and carves the plaintext media carriers (Bink2 video, AWC audio) that the
archives store without encryption.

Deliberately dependency-free: standard library only.
"""

__version__ = "1.0.0"
__all__ = ["rpf", "rds5", "gfx10", "texture", "psin", "media", "shaders",
           "structured", "embedded", "models", "inventory", "report", "cli",
           "tui"]
