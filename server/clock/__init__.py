"""Authoritative game clock, 48-minute game-day tick."""
from . import core

def migrations():
    return []

def register(registry):
    registry.flag('clock_enabled', True)
