r"""Moved to tools\make_workshop.py at the top of the repository (shared by the mods there).
This stub keeps the old command working from the Smoker folder:
  python tools\make_workshop.py [dest folder]
"""
import runpy
import sys
from pathlib import Path

MOD = Path(__file__).resolve().parent.parent
SHARED = MOD.parent / 'tools' / 'make_workshop.py'
args = [str(MOD)]
if len(sys.argv) > 1:
    args += ['--dest', sys.argv[1]]
sys.argv = [str(SHARED)] + args
runpy.run_path(str(SHARED), run_name='__main__')
