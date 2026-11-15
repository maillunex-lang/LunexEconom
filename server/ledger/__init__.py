"""Ledger module: zero-sum, integer postings."""
from pathlib import Path
from . import api

def migrations():
    return [Path(__file__).resolve().parents[1] / 'migrations' / '202611150901_ledger_journal.sql']

def register(registry):
    registry.flag('ledger_enabled', True)
