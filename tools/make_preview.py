r"""Moved to tools\make_preview.py at the top of the repository (shared by the mods there).
This stub keeps the old command working from the Smoker folder:
  python tools\make_preview.py [art/smoker.png]
Needs Pillow (python, not python -I).
"""
import runpy
import sys
from pathlib import Path

MOD = Path(__file__).resolve().parent.parent
SHARED = MOD.parent / 'tools' / 'make_preview.py'
picture = sys.argv[1] if len(sys.argv) > 1 else str(MOD / 'art' / 'smoker.png')
sys.argv = [str(SHARED), picture, '--folder', str(MOD)]
runpy.run_path(str(SHARED), run_name='__main__')
