# Sentinel pcap summary - 01_read_from_scanner.pcap

- Capture file: `AI\Dev\RE\sentinel_pcaps\01_read_from_scanner.pcap`
- SCSI command frames: 51
- READ_10 commands: 9 (42,496 B)
- WRITE_10 commands: 3 (12,288 B)
- Max LBA touched: 0x0003EEC2 = sector 257730 = byte 131,958,272
- Files identified in FAT32 walk: 0

## SCSI command-kind histogram

| Operation | Count |
|---|---:|
| `TEST_UNIT_READY` | 24 |
| `REQUEST_SENSE` | 14 |
| `READ_10` | 9 |
| `WRITE_10` | 3 |
| `MODE_SENSE_6` | 1 |

