# DEPRECATED: import from core.metastore. Root shim removed next release.
import core.metastore as _mod
import sys

sys.modules[__name__] = _mod
