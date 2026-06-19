# DEPRECATED: use legacy_tk.scanner_manager. Root shim removed next release.
import legacy_tk.scanner_manager as _mod
import sys

sys.modules[__name__] = _mod
