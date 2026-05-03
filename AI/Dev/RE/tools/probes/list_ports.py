"""Throwaway: list USB serial ports with VID/PID for SDS100 detection."""
import serial.tools.list_ports as lp

UNIDEN_VID = 0x1965
ports = sorted(lp.comports(), key=lambda p: p.device)
for p in ports:
    if p.vid is None:
        continue
    is_sds = p.vid == UNIDEN_VID
    tag = " <-- SDS100" if is_sds else ""
    print(
        f"{p.device}  vid=0x{p.vid:04x}  pid=0x{p.pid:04x}  "
        f"desc={p.description!r}  ser={p.serial_number}{tag}"
    )
