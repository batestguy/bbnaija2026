import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Test-suite speed: the P5 model graphs cost ~5 min each to C-compile under
# bap3's NumPy-C-API BLAS. FAST_COMPILE keeps the graph in Python — fine for
# 120-draw sanity runs, wrong for real sampling (the CLI never sets this).
os.environ.setdefault("PYTENSOR_FLAGS", "mode=FAST_COMPILE")
