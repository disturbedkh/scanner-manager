# DEPRECATED: import from core.app_updater. Root shim removed next release.
import core.app_updater as _mod
import sys

sys.modules[__name__] = _mod
