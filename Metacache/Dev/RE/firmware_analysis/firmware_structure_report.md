# Firmware structural analysis

## main_1.23.07

- File: `SDS-100_V1_23_07.bin`
- Size: **2,162,688** bytes
- Whole-file Shannon entropy: **7.9999** bits/byte (max 8)
- 4 KiB chunk entropy: 528 high(>=7.5), 0 mid, 0 low(<4) of 528 total

### First 64 bytes
```
  00000000  6c 6f 53 65 c3 07 ee 94 02 18 b7 2b ac b8 a3 71   |loSe.......+...q|
  00000010  ef 56 4e 1a 7e b0 97 cd 7e b2 4b c7 dc b4 28 62   |.VN.~...~.K...(b|
  00000020  dd 90 6e 81 7d 89 70 f2 34 d6 5e 2b 94 2f d5 ab   |..n.}.p.4.^+./..|
  00000030  35 b0 1e b4 03 5f 9e 1e 64 cc 36 fb eb 46 f0 08   |5...._..d.6..F..|
```

### Last 64 bytes
```
  0020ffc0  01 bc 30 c3 76 04 a8 45 ed ba 11 e3 53 e9 8c 33   |..0.v..E....S..3|
  0020ffd0  5a 82 16 4f 8c bc 4f 92 d8 5d 9e e8 22 70 ec c3   |Z..O..O..].."p..|
  0020ffe0  0e 38 c3 32 6c b9 26 f5 ec 2b aa 06 49 7b 0b 63   |.8.2l.&..+..I{.c|
  0020fff0  9d dc 55 9e e8 65 a1 08 42 74 04 a6 34 d1 09 88   |..U..e..Bt..4...|
```

### Magic-byte signature hits (first 32)
```
  0x00008a83  gzip
  0x0000924b  zlib (default)
  0x0001560e  zlib (low compression)
  0x00018804  zlib (default)
  0x00018c29  zlib (default)
  0x0001c6e1  zlib (default)
  0x0001d5ac  gzip
  0x000230e0  zlib (default)
  0x00036301  zlib (default)
  0x00049627  gzip
  0x0005a107  zlib (default)
  0x00069346  zlib (default)
  0x00071fec  zlib (default)
  0x00080612  zlib (default)
  0x00080707  gzip
  0x00090d67  gzip
  0x000a2aa9  gzip
  0x000a6ef1  zlib (default)
  0x000ad314  gzip
  0x000b151d  gzip
  0x000ba732  zlib (default)
  0x000bc9c5  zlib (default)
  0x000c559f  gzip
  0x000d75e0  zlib (default)
  0x000ddf28  zlib (default)
  0x000debfb  zlib (default)
  0x000e1988  zlib (default)
  0x000ebc50  gzip
  0x000ecfaa  zlib (default)
  0x000ee3f8  zlib (default)
  0x000f239e  gzip
  0x000f53d0  zlib (default)
```

## main_1.26.01

- File: `SDS-100_V1_26_01.bin`
- Size: **2,162,688** bytes
- Whole-file Shannon entropy: **7.9999** bits/byte (max 8)
- 4 KiB chunk entropy: 528 high(>=7.5), 0 mid, 0 low(<4) of 528 total

### First 64 bytes
```
  00000000  00 d0 ea 9a 22 26 9f 76 f4 bc 00 ea 40 9d 13 c4   |...."&.v....@...|
  00000010  a5 a6 8d 96 ca 3f 55 04 3e 77 11 86 fd 62 89 5a   |.....?U.>w...b.Z|
  00000020  67 87 37 ea 1c 34 3a 06 6b 0f 49 16 65 ce e3 ec   |g.7..4:.k.I.e...|
  00000030  58 47 31 19 28 2f 48 99 de 08 9c b6 b6 70 7f 6e   |XG1.(/H......p.n|
```

### Last 64 bytes
```
  0020ffc0  c5 f8 04 37 52 60 9c b1 e9 3e 25 17 77 8d b8 c7   |...7R`...>%.w...|
  0020ffd0  7d 04 69 e1 95 3c 8e dc 87 71 69 c2 63 18 55 d0   |}.i..<...qi.c.U.|
  0020ffe0  64 f9 41 b3 46 ca 34 b4 94 38 7a e9 75 16 6f ca   |d.A.F.4..8z.u.o.|
  0020fff0  6d 13 4d 95 54 a8 35 99 3a d7 24 3a 68 8d 33 a0   |m.M.T.5.:.$:h.3.|
```

### Magic-byte signature hits (first 32)
```
  0x000038ac  zlib (low compression)
  0x00005924  gzip
  0x0000a687  gzip
  0x00010e24  zlib (default)
  0x0001530e  zlib (low compression)
  0x0001816c  gzip
  0x0001ba06  gzip
  0x0001edd6  gzip
  0x000236e8  gzip
  0x00024346  zlib (default)
  0x0003e567  gzip
  0x00049184  zlib (default)
  0x0004b76e  zlib (default)
  0x000530be  gzip
  0x0005d786  zlib (default)
  0x0007311d  zlib (default)
  0x00076c83  gzip
  0x0007cdca  zlib (default)
  0x00082139  gzip
  0x00083220  gzip
  0x0008550b  zlib (default)
  0x00089caf  zlib (default)
  0x000914ce  zlib (default)
  0x00091bba  gzip
  0x0009861a  zlib (default)
  0x000a6b7e  gzip
  0x000afe92  zlib (default)
  0x000b32a3  zlib (default)
  0x000bbd5e  gzip
  0x000c59ac  gzip
  0x000d0750  gzip
  0x000d22c1  gzip
```

## sub_1.03.05

- File: `SDS-100-SUB_V1_03_05.firm`
- Size: **88,864** bytes
- Whole-file Shannon entropy: **7.1807** bits/byte (max 8)
- 4 KiB chunk entropy: 0 high(>=7.5), 22 mid, 0 low(<4) of 22 total

### First 64 bytes
```
  00000000  53 44 53 2d 31 30 30 2d 53 55 42 00 ff ff ff ff   |SDS-100-SUB.....|
  00000010  ff ff ff ff ff ff ff ff 56 65 72 73 69 6f 6e 20   |........Version |
  00000020  31 2e 30 33 2e 30 35 20 00 01 5a 14 00 00 00 80   |1.03.05 ..Z.....|
  00000030  00 01 5a a0 ff ff ff ff ff ff ff ff ff ff ff ff   |..Z.............|
```

### Last 64 bytes
```
  00015ae0  ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff   |................|
  00015af0  ff ff ff ff ff ff ff ff ff ff ff ff ca 25 26 c3   |.............%&.|
  00015b00  53 44 53 2d 31 30 30 2d 53 55 42 00 ff ff ff ff   |SDS-100-SUB.....|
  00015b10  ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff   |................|
```

### Magic-byte signature hits (first 32)
```
  0x000001bc  ARM Cortex-M reset vector candidate (SP at 0x20000000)
  0x00000204  ARM Cortex-M reset vector candidate (SP at 0x20000000)
  0x00000a41  zlib (low compression)
  0x00000bed  zlib (low compression)
  0x00000ed9  zlib (low compression)
  0x000011dd  zlib (low compression)
  0x00001379  zlib (low compression)
  0x000019a7  zlib (low compression)
  0x00001b31  zlib (low compression)
  0x000024a9  zlib (low compression)
  0x00002743  zlib (low compression)
  0x0000305d  zlib (best compression)
  0x000033e3  zlib (low compression)
  0x00003df7  zlib (low compression)
  0x000040f3  zlib (low compression)
  0x00004371  zlib (low compression)
  0x00004707  zlib (low compression)
  0x00004c87  zlib (low compression)
  0x000050bb  zlib (low compression)
  0x00005345  zlib (low compression)
  0x000055d0  zlib (low compression)
  0x00005fc0  ARM Cortex-M reset vector candidate (initial SP at 0x20001000)
  0x000066a7  zlib (low compression)
  0x00006fcb  zlib (low compression)
  0x000076b9  zlib (low compression)
  0x00007be2  LZMA1 (literal context bits)
  0x00007c42  LZMA1 (literal context bits)
  0x00007d0e  LZMA1 (literal context bits)
  0x00008463  zlib (low compression)
  0x000097f3  zlib (low compression)
  0x000097fb  zlib (low compression)
  0x00009803  zlib (low compression)
```

## sub_1.03.15

- File: `SDS-100-SUB_V1_03_15.firm`
- Size: **90,464** bytes
- Whole-file Shannon entropy: **7.1813** bits/byte (max 8)
- 4 KiB chunk entropy: 0 high(>=7.5), 22 mid, 1 low(<4) of 23 total

### First 64 bytes
```
  00000000  53 44 53 2d 31 30 30 2d 53 55 42 00 ff ff ff ff   |SDS-100-SUB.....|
  00000010  ff ff ff ff ff ff ff ff 56 65 72 73 69 6f 6e 20   |........Version |
  00000020  31 2e 30 33 2e 31 35 20 00 01 60 5c 00 00 00 80   |1.03.15 ..`\....|
  00000030  00 01 60 e0 ff ff ff ff ff ff ff ff ff ff ff ff   |..`.............|
```

### Last 64 bytes
```
  00016120  ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff   |................|
  00016130  ff ff ff ff ff ff ff ff ff ff ff ff 57 e6 b5 2a   |............W..*|
  00016140  53 44 53 2d 31 30 30 2d 53 55 42 00 ff ff ff ff   |SDS-100-SUB.....|
  00016150  ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff   |................|
```

### Magic-byte signature hits (first 32)
```
  0x000001bc  ARM Cortex-M reset vector candidate (SP at 0x20000000)
  0x00000204  ARM Cortex-M reset vector candidate (SP at 0x20000000)
  0x00000a41  zlib (low compression)
  0x00000bed  zlib (low compression)
  0x00000ed9  zlib (low compression)
  0x000011dd  zlib (low compression)
  0x00001379  zlib (low compression)
  0x000019a7  zlib (low compression)
  0x00001b31  zlib (low compression)
  0x000024a9  zlib (low compression)
  0x00002743  zlib (low compression)
  0x0000305d  zlib (best compression)
  0x000033e3  zlib (low compression)
  0x00003df7  zlib (low compression)
  0x000040f7  zlib (low compression)
  0x00004375  zlib (low compression)
  0x000046fb  zlib (low compression)
  0x0000477f  zlib (low compression)
  0x00004cc7  zlib (low compression)
  0x000050fb  zlib (low compression)
  0x00005385  zlib (low compression)
  0x00005610  zlib (low compression)
  0x00006008  ARM Cortex-M reset vector candidate (initial SP at 0x20001000)
  0x0000673b  zlib (low compression)
  0x00006fb9  zlib (best compression)
  0x00007023  zlib (low compression)
  0x00007735  zlib (low compression)
  0x00007c62  LZMA1 (literal context bits)
  0x00007cc2  LZMA1 (literal context bits)
  0x00007d36  LZMA1 (literal context bits)
  0x00007dd6  LZMA1 (literal context bits)
  0x00008faf  zlib (low compression)
```

## Byte-level diff: main_1.23.07 -> main_1.26.01

- Same size: 2,162,688 bytes
- Bytes changed: **2,154,230** (99.61% of file)
- Number of changed runs: **8429**
- Top 20 longest changed runs (offset, length):

| Offset | Length | Pct of file |
| --- | --- | --- |
| `0x000f7114` | 2,254 | 0.10% |
| `0x00087420` | 2,153 | 0.10% |
| `0x000625ce` | 2,128 | 0.10% |
| `0x0001edcc` | 1,956 | 0.09% |
| `0x00198e58` | 1,953 | 0.09% |
| `0x00036ea8` | 1,939 | 0.09% |
| `0x0003fba0` | 1,921 | 0.09% |
| `0x000fb214` | 1,784 | 0.08% |
| `0x000dc661` | 1,724 | 0.08% |
| `0x001d12b9` | 1,701 | 0.08% |
| `0x0005a273` | 1,695 | 0.08% |
| `0x0000c3c3` | 1,687 | 0.08% |
| `0x001f8b76` | 1,684 | 0.08% |
| `0x000955aa` | 1,663 | 0.08% |
| `0x000daf92` | 1,660 | 0.08% |
| `0x000a589b` | 1,656 | 0.08% |
| `0x0010d7d6` | 1,653 | 0.08% |
| `0x000028b8` | 1,652 | 0.08% |
| `0x000a522e` | 1,644 | 0.08% |
| `0x0001d25b` | 1,629 | 0.08% |

## Byte-level diff: sub_1.03.05 -> sub_1.03.15

- Different sizes: 88,864 -> 90,464 bytes (delta +1,600)
- Cannot do byte-aligned diff directly. Skipping.
