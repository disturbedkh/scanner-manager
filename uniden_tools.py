# DEPRECATED: import from core.uniden_tools. Root shim removed next release.
import core.uniden_tools as _mod
import sys

sys.modules[__name__] = _mod
