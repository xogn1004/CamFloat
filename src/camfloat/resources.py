"""Resolve bundled assets independently of the current working directory."""
from pathlib import Path
import sys


def asset_path(name):
    root = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[2]
    return root / 'assets' / name
