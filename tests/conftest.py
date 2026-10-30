"""Make the repository root importable so tests can import config and codebook."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
