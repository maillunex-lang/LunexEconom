"""Ledger module: zero-sum, integer postings."""
from pathlib import Path
from . import api

def migrations():
    return [Path(__file__).resolve().parents[1] / 'migrations' / '202611150901_ledger_journal.sql', Path(__file__).resolve().parents[1] / 'migrations' / '202611151001_ledger_v201.sql']

def register(registry):
    registry.flag('ledger_enabled', True)
    registry.route('GET','/ledger/balance',api.balance)
    registry.route('GET','/ledger/history',api.history)
