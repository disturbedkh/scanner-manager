"""Quick parser-pattern inspector for one decompiled function."""
import json
import re
import sys
from pathlib import Path

target = sys.argv[1] if len(sys.argv) > 1 else "0x14009100"
norm = target.lower().replace("0x", "").replace("fun_", "")
ROOT = Path(__file__).resolve().parents[3]
DEC = ROOT / "AI" / "Dev" / "RE" / "firmware" / "decompiles"
matches = list(DEC.glob(f"{norm}*.json"))
if not matches:
    sys.exit(f"No decompile found for {target}")

data = json.loads(matches[0].read_text(encoding="utf-8"))
d = data.get("decompile", "") or ""
print(f"// {matches[0].name}")
print(f"// addr={data.get('addr')} size={data.get('size')} "
      f"callers={len(data.get('callers', []))} callees={len(data.get('callees', []))}")
print(f"// peripherals={data.get('peripheral_accesses', [])}")
print()

cmp_chars = sorted(set(re.findall(r"== '(.)'", d)))
cmp_hex = sorted(set(re.findall(r"== 0x([0-9a-fA-F]{1,2})\b", d)))
print(f"== Char-cmp count: {d.count('== ')}  unique chars={cmp_chars}  unique hex={cmp_hex}")
print()
print("---- decompile (first 6000 chars) ----")
print(d[:6000])
