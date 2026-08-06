"""EFS-C651-EU smart fitness scale support."""

from . import protocol
from .scale import EFSC651Scale

__all__ = ["EFSC651Scale", "protocol"]
