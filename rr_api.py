# DEPRECATED: import from core.rr_api. Root shim removed next release.
import core.rr_api as _mod
import sys

sys.modules[__name__] = _mod
