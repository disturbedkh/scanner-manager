# DEPRECATED: import from core.coverage_maps. Root shim removed next release.
import core.coverage_maps as _mod
import sys

sys.modules[__name__] = _mod
