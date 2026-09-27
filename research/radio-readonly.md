# First physical CI-V status read — 2026-09-20

After the owner confirmed USB SEND and both USB keying options OFF, with the
connection inhibit timer ON, the host rechecked the original IC-7300 CP2102
interface and opened its current serial port exclusively. No competing process
was reported by `lsof`. PySerial 3.5 was installed only in the project virtual
environment. Host framing was 19200 baud, 8N1, with RTS and DTR set false before
opening, no software or hardware flow control, and bounded read/write timeouts.

Only two request frames were sent, to radio address 0x94 from controller 0xe0:
command 0x03 (operating frequency) and command 0x04 (operating mode). Each returned
a corresponding response with the expected source/destination addresses and frame
terminator. The port was closed after the queries. No setting, PTT, tuning,
firmware or memory-write commands were sent. Exact frames, observed operating
values, timestamp and host device path remain in ignored local evidence:
`artifacts/radio-status-first-read.json`.

Command definitions and response encoding were checked against the manufacturer
[full manual](https://icomuk.co.uk/files/icom/PDF/advancedManuals/IC-7300_ENG_FM_12a.pdf),
section 19, command table p. 19-3 and data encoding p. 19-9. The downloaded manual
is kept under ignored `artifacts/docs/`.

Result: physical CI-V status communication established on the owner's stock
radio. This does not establish flash/RAM readback, calibration backup, selector
contents, audio performance, runtime headroom or application-independent recovery.
The previous 1.42 version observation remains photographic evidence; these two
queries do not report the installed firmware version. No automatic polling or
persistent serial session remains running.
