"""EFS-A591S-KUS (Apex HR Smart Fitness Scale) support."""

from . import protocol
from .scale import EFSA591SScale

__all__ = [
    "EFSA591SScale",
    "protocol",
]
