# DEPRECATED: import from core.sdcard. Root shim removed next release.
import core.sdcard as _mod
import sys

sys.modules[__name__] = _mod
