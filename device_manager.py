# DEPRECATED: import from core.device_manager. Root shim removed next release.
import core.device_manager as _mod
import sys

sys.modules[__name__] = _mod
