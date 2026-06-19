# SUB Dispatch Verification - 20260503T134023Z

- Port: `COM3` @ 115200
- Anchor: `SDS100-SUB`
- Candidates probed: 12
- Classifications: HIT=10 ERR=0 IDENTITY=0 TIMEOUT=2

## HIT (likely real undocumented commands)

| Mnemonic | Time (ms) | First response line |
|---|---:|---|
| `o` | 253 | `` |
| `q` | 189 | `` |
| `w` | 190 | `` |
| `d` | 376 | `` |
| `r` | 188 | `-4921` |
| `m` | 381 | `` |
| `z` | 252 | `` |
| `l` | 632 | `` |
| `s` | 461 | `2179540746614390010000000.000000, 1646510080.000000, 0` |
| `v` | 231 | `` |

## ERR (recognised mnemonic; likely needs arguments)

| Mnemonic | Time (ms) | Response |
|---|---:|---|
| _(none)_ | | |

## IDENTITY (anchor leakage; mnemonic NOT recognised)

_The SUB port returns the previous response (`SDS100-SUB`) when_ _it doesn't recognise the input. 0 mnemonics fall here, and these_ _are evidence that Ghidra's heuristic over-reached._

<details><summary>List (0 mnemonics)</summary>

</details>

## TIMEOUT

<details><summary>List (2 mnemonics)</summary>

- `t`
- `u`
</details>

