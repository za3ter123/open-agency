"""Put projects/agency on sys.path so `import leadengine` works when tests are
discovered from C:\\Users\\Win (parent of projects/agency)."""
import os
import sys

_AGENCY_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _AGENCY_ROOT not in sys.path:
    sys.path.insert(0, _AGENCY_ROOT)
