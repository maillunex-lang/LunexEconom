"""Authoritative 48-minute days and atomic ordered tick workers."""
from . import core

def migrations():
    return []

def register(registry):
    registry.flag('clock_enabled', True)
    registry.route('GET','/clock',core.get_clock)
