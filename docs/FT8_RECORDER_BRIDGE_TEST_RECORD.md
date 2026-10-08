# Offline recorder-audio FT8 bridge test record

- **Issue and scope:** Related to [#15](https://github.com/zarthur/ic-7300_firmware/issues/15), receive-audio capture. This desktop bridge advances offline audio handling; it does not meet the issue's timestamped native-capture acceptance.
- **Source revision:** Based on `34404a2f284a2fcb6444cb0a0016dca2f22c4100` (PR #87) with this change set; tested 2026-10-08.
- **Phase:** Desktop and synthetic data only. TX authorized: **no**.
- **Target:** Portable FT8 prototype, a generated 12 kHz FT8 waveform, synthetic 8 kHz PCM16 audio, and synthetic complete v1 diagnostic carrier frames. No radio or firmware image target.
- **Purpose and expected results:** Verify complete carrier/checksum validation, sample-aligned carrier removal, separate audio segments around the carrier, 8-to-12 kHz resampling, decoder acceptance of the generated message from intact recorder audio, and fail-closed handling of unsupported v3 frames. The bridge must not assign UTC or join audio across removed carrier bytes.
- **Prerequisites:** Pinned `ft8_lib`, Python with NumPy and SciPy, and the host C toolchain. Radio, backup, recovery, operator, instruments, hardware stop control and TX prerequisites: **N/A**; the tests are desktop-only.
- **Procedure:** `python3 tools/development_check.py --profile full --output artifacts/ft8-recorder-audio-bridge-validation`
- **Stop conditions:** Stop on any failed check, malformed or incomplete carrier accepted, audio joined across the carrier, generated FT8 message missed, unsupported carrier accepted, or any unexpected hardware access.
- **Results:** Full profile passed: 354 Python tests, zero failures, errors or skips; all 17 project checks passed, including sanitizers, firmware roundtrips and reference comparison. The focused integration fixture decoded `CQ K1ABC FN42` from synthetic ordinary recorder audio after a valid carrier. Input data was synthetic and no UTC was assigned.
- **Limitations and follow-up:** This does not decode native stream A directly, establish native sample-to-UTC timing, qualify live radio receive, or demonstrate on-radio FT8. Stream B meaning and the live DSP/audio path remain unresolved. Issue #15 remains open; its timestamped receive-only capture acceptance still requires separate hardware evidence.
- **Outcome:** PASS for the offline desktop bridge only. No hardware approval or RF authorization is implied.
