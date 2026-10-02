# Issue #18: host-only RAM feature-state seam

The issue asks for UI callbacks/rendering and settings-persistence interfaces,
safe integration hooks, a RAM-only feature-state plan, and a minimal UI hook.
This change implements only a portable host-prototype seam. It does not connect
to an IC-7300 menu, display, key, settings record, or storage service.

## State contract

- Initialize `ft8_ui_state` once at startup. It is enabled only by an explicit
  `FT8_UI_ACTION_ENABLE`; its safe default is disabled.
- Enable dispatch requires an initialized QSO and an explicit time-quality
  policy. It delegates to the existing `qso_enable` guard and never creates a
  reservation, generates audio, controls PTT, or transmits.
- Enable is refused while the station is awaiting backend abort/flush
  confirmation; the UI seam does not bypass the station's output-reuse fence.
- Cancel dispatch delegates to `station_cancel`, leaves feature state disabled,
  and is idempotent. Existing station/backend lifecycle rules remain responsible
  for abort and flush acknowledgement before a later session can reuse output.
- Reset cancels the current station session and returns the volatile feature
  state to disabled. Boot and reset have no persisted representation; no settings
  or SD APIs are called.
- The caller serializes dispatch with station/QSO operations, matching the
  existing host station contract. The API is not interrupt-safe.

`ft8_ui_dispatch` is the only prospective hook surface in this change. A future
adapter may map a verified UI event to enable/cancel. No live menu callback or
rendering path is asserted by this API.

## Native boundary still open

The display-label investigation reaches the renderer entry using synthetic menu
state and stops before rendering; live row construction and callback ownership
remain unobserved. The recorder-controls study identifies selected settings
records and their value/label pointers, but does not execute menu changes or
option rendering. The general settings-persistence format and a safe native UI
callback are not established. Therefore this host seam is not a native UI hook
and does not complete #18 acceptance.

The first native follow-up should trace one specific UI event from its original
producer through dispatch to renderer/state consumer, including execution
context and reset lifetime. Keep feature state in the portable volatile object
until that path and its storage boundaries are verified. Do not write existing
settings records or infer unused menu rows from strings alone.

## Host checks

`tests/test_ui_state.c` covers boot defaults, policy-required enable, cancel,
reset, idempotent repeated commands, invalid inputs and external QSO
invalidation. Tests leave the station backend idle and perform no audio output.
