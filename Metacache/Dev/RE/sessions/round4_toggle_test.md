# Round 4 toggle test - t/u mode flags

Hypothesis: t toggles a byte 0<->1, u toggles 0<->2. The byte is consulted by q/r and possibly other dump commands. Comparing q and r outputs across toggle states should reveal the dependency.

| Step | Sent | Bytes | First 16 hex | Lines | First line |
|---|---:|---:|---|---:|---|
| baseline q | `q` | 1462 | `0d0a2d323634310d2d343930310d2d39` | 260 | `` |
| after t#1 | `t` | 0 | `` | 0 | `` |
| q (mode B) | `q` | 1454 | `0d0a313533320d3830380d3538360d31` | 260 | `` |
| after t#2 | `t` | 0 | `` | 0 | `` |
| q (back) | `q` | 1418 | `0d0a363230340d31303934320d313439` | 260 | `` |
| after u#1 | `u` | 0 | `` | 0 | `` |
| q (mode C) | `q` | 1532 | `0d0a333639370d323538360d3733330d` | 260 | `` |
| after u#2 | `u` | 0 | `` | 0 | `` |
| q (back2) | `q` | 1483 | `0d0a2d393730350d2d31333934340d2d` | 260 | `` |
| baseline r | `r` | 1590 | `2d343932310d2d32353534390d313834` | 256 | `-4921` |
| after t#3 | `t` | 0 | `` | 0 | `` |
| r (mode B) | `r` | 1590 | `2d343932310d2d32353534390d313834` | 256 | `-4921` |
| after t#4 | `t` | 0 | `` | 0 | `` |
| r (back) | `r` | 1590 | `2d343932310d2d32353534390d313834` | 256 | `-4921` |

## Analysis

### `q` byte-count by toggle state

- baseline q: 1462 B, first_line ``
- q (mode B): 1454 B, first_line ``
- q (back): 1418 B, first_line ``
- q (mode C): 1532 B, first_line ``
- q (back2): 1483 B, first_line ``

**Conclusion: q output VARIES across toggle states - t and/or u DO modify q's output format/content.**

### `r` byte-count by toggle state

- baseline r: 1590 B, first_line `-4921`
- r (mode B): 1590 B, first_line `-4921`
- r (back): 1590 B, first_line `-4921`

