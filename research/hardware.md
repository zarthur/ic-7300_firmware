# Hardware evidence and FT8 placement

Icom service manual, PDF pages 22 (parts), 60 (block diagram 9-2), 64/66/68
(schematics), inspected as text and rendered block diagram:
https://www.rigpix.com/icom/ic7300_service.pdf
SHA-256: `223b21ee6566a143252eb8e5f92e15c277c7842732fde403f31cba389c74c171`.
This is Icom-authored primary documentation hosted by a third party; board
revisions must be checked against the eventual development radio.

| Reference | Part identified by service manual | Implication |
|---|---|---|
| IC301 | Renesas R7S721000VCFP | RZ/A1H Cortex-A9, 10 MB on-chip SRAM, rated up to 400 MHz; actual configured clock/headroom unmeasured |
| IC901 | TI TMS320C6745DPTPA3 | C674x DSP, 32 KiB L1P, 32 KiB L1D, 256 KiB L2 RAM/cache; no C6747-only extra 128 KiB |
| IC391 | EN25Q64 | Main serial flash; capacity and exact revision should be verified from original part datasheet before programming |
| IC902 | EN25QH32A | DSP-side serial flash; distinct from main flash |
| IC1351 | Altera EP4CE55F23I7N | Cyclone IV FPGA in the RF sample-processing path |
| IC1401 | Microchip 23LC1024T | 1 Mbit (128 KiB) serial SRAM attached to FPGA, not general CPU heap |
| IC351 | GT24C128B-2ZLI-TR | Separate main-board EEPROM; calibration/configuration ownership and backup coverage unresolved |
| J491 | 10FLT-SM2-TB connector | Main CPU debug nets in service schematic; physical access and recovery unqualified |
| IC381 | Epson RX-8803LC | I2C RTC with 1/100-second register and IRQ connection to CPU |

Primary chip references:

- https://www.renesas.com/en/products/rz-a1h/part-details/r7s721000vcfp-ba1
- https://www.ti.com/lit/ds/symlink/tms320c6745.pdf
- https://www.microchip.com/en-us/product/23lc1024
- https://www.epsondevice.com/crystal/en/products/rtc/rx8803lc.html
- https://esmt.com.tw/upload/pdf/ESMT/datasheets/EN25QH32A_Ver.C.pdf

The ESMT flash datasheet link was found but could not be downloaded as a valid
PDF on this host (certificate failure at the bare domain, invalid document from
the www host). Flash identities above are verified from Icom's manual; detailed
flash geometry/programming requirements remain pending primary datasheets.

The 48 MHz crystal shown beside IC301 is not evidence that the CPU runs at
48 MHz; clock/PLL registers need decoding. SRAM capacity is not free memory.
The current floating-point decoder's ~236 KiB requested heap plus scratch,
context, and radio workload makes a DSP-only implementation unattractive without
substantial optimization and a verified memory map. Investigate Cortex-A9 first.

The block diagram exposes CPU/DSP connections labeled DR_AF/DR_RSV/DX_REC/DX_FMT
and HSK0/HSK1/DRESD/FRWT, and a separate DSP/FPGA serial audio path. Recorder and
voice-playback code are promising routes into existing audio handling. Neither
the wire format nor the DMA/sample-buffer ownership is established yet.

RTC subsecond capability supports a plausible standalone timing design. The
specific fitted accuracy grade, oscillator health and firmware register usage
are not known. Use operator-set UTC with a subsecond adjustment control, latch
RTC time against a monotonic hardware timer, and apply corrections only while
TX is disabled. A time step invalidates pending TX. Measure drift and scheduling
latency on hardware before selecting a resynchronization interval. No network
or external computer is part of the intended operating path.

See [recovery-access.md](recovery-access.md) for the later J491/EEPROM review and
the distinction between adjustment mode, debug access and demonstrated recovery.
