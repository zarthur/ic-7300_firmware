# Other-component selection boundary — bounded follow-up

Baseline investigated: `e4dfee35c63b5eeb1e6e5dfbd066ab47318355ac`, exact registry-validated original v1.42 image. No radio I/O, firmware modification, third-party contact or physical updater experiment occurred.

## Finding

`0x20021ff0..0x2002200c` is a three-entry component-change flag getter, not a component-update handler. It reads the indexed byte at `0x2039013a` for indices below three and returns zero otherwise. The existing main updater harness substituted zero at this boundary; the follow-up executes the original getter with explicitly modeled zero RAM flags. Its ordinary main update still returns successfully in the covered model without entering selected-component dispatch.

The earlier header precheck (`0x200253f4..0x20025604`) compares three container identifiers with supplied installed identifiers. On the same unchanged official file, supplying matching installed identifiers yields flags `[0,0,0]`; changing one supplied identifier yields the corresponding single flag. Four original-instruction checks confirm this. Installed identifiers remain model inputs, not measured radio RAM.

Thus “DSP/FPGA source bytes were not changed” is insufficient to establish that the stock updater skips those components. Skip is conditional on the selected flags/installed identity state. No byte-for-byte installed DSP/FPGA flash comparison has been demonstrated here.

## Actual dispatch boundary

The original caller at `0x20025f24..0x20025f70` calls the getter and copies flags into a local array. At the first nonzero flag it writes value two to the handshake byte at `0x20390308` and waits at `0x20025f5c`. The local probe stops there without fabricating acknowledgment or task/device responses. Entries after that first nonzero flag retain a synthetic sentinel, and must not be interpreted as observed component selection.

All eight boolean flag combinations were checked. The all-zero case reads all three flags and reaches the component loop at `0x20025f70`; the seven nonzero cases stop at the unresolved handshake boundary. The loop checks each local flag at `0x20025f70..0x20025f78`; zero branches past component processing to `0x200260a8`. This is original instruction execution under explicit memory/setup models, not live update reachability or hardware acceptance.

The complete main-update harness now executes the original getter with zero flags, rather than substituting its return. Other file services, main transfers, setup and activation call effects retain their existing models. The selected-component handler remains unexecuted.

## Selected-component work still unresolved

Bounded static inspection of the subsequent caller (`0x20025f70..0x200260b8`) shows a selected component causes a seek, payload and expected-digest read, payload digest comparison, then a call at `0x20026090` to `0x20025044`. The helper range inspected, `0x20025044..0x20025288`, contains staging/chunk handling and calls into asynchronous/device-related helper families. Those callees and their physical consequences are not qualified by this pass. We do not infer an erase map, target memory type, actual DSP/FPGA rewrite, or safe interruption behavior from this inspection.

The exact upstream writer of the handshake acknowledgment, live installed identifiers, selected-component protocol and device completion/error behavior remain the next concrete questions. Do not force the handshake clear to claim a successful whole update. No broad additional scan is required in this increment.

## Implementation and validation

The bounded implementation is `component_dispatch_boundary()` in `tools/updater_stages.py`. It requires the exact decoded application hash, supplies flags/local workspace/initial handshake state, executes only reviewed instruction windows, and enforces 1,000 instructions and one second. A setup-return model is used only on the zero-flags branch. A nonzero result is `UNRESOLVED_HANDSHAKE`, not PASS or accepted updater execution.

`tests/test_updater_stages.py` covers identifier-derived flags, all eight dispatch combinations, exact-image/flag rejection and the existing full-main model using the real getter. All 11 tests in that module passed with the pinned image, zero skips. The synthetic profile includes `test_updater_stages.ComponentDispatchModelTests` so hosted CI exercises the input guards without vendor firmware; the original-image tests remain local-only.

