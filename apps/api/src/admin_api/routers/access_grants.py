"""Módulo de concesiones de acceso a datos de cliente (§18.13 – §18.15, ticket B2-05).

Reexporta el router canónico definido en grants.py para cumplir con ambas
nomenclaturas de módulo en la API administrativa.
"""

from .grants import *  # noqa: F403
from .grants import router  # noqa: F401
