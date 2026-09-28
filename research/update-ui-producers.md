# Bounded normal-UI producer investigation

Checkout: `8f8e921` in `/Users/arthur/Documents/projects/ic-7300-development`. Exact pinned v1.42 image: SHA-256 `8cf5324a126f105cd2307c30b191b9dd8183f86b2c8bf229e61bf9a6a8c32f32`. Reproduce the six bounded states with `tools/update_dispatch.py`. No modified images or device access.

## New concrete producer map

The dispatcher context is `0x2039011c`, with its command word at +0x44. Three original wrappers copy a supplied path through helper `0x2017c860`, store a literal command, then tail-call the common wake/signal path `0x200223ec`:

| Wrapper | Command stored | Bounded ARM direct caller sites |
| --- | --- | --- |
| 0x20022f78 | 38 / header check | 0x2005b354, 0x2005b3b4 |
| 0x20022f9c | 39 / payload check | 0x2005b438 |
| 0x20022fc0 | 11 / main update | 0x2005b4a8 |

These are static original-code relationships. The wrappers' path-copy and wake helpers were not executed here, and the scan is not a complete mixed-ISA or indirect caller inventory.

Their callers lie in a UI state function beginning `0x2005b2a0`, using state byte `0x20390368`. This changes the next question from finding arbitrary command writers to specific UI-state predicates.

## Local UI predicates and executed evidence

Six bounded executions start at the original function entry with explicitly seeded UI state and command/handshake RAM. No unknown helper is replaced by success; execution stops before an unreviewed callee. Thus these results are *local state reachability*, not proof of normal UI entry or a live installation workflow.

- State 0x35 reaches the header producer at 0x20022f78, before any command is written.
- State 0x39 stops at predicate 0x20059090 before payload submission. Static follow-up shows a tail-call to 0x20059060, which requires helper 0x20047f08 to return nonzero and helper 0x2000a23c to return zero. Those helper semantics are unresolved here. A subsequent 0x20021500 gate behaves as a byte test-and-set on context +4; its runtime scheduling meaning is not established.
- State 0x3a invokes the original command-status reader 0x20023414. With command word zero, it returns normally after advancing UI state to 0x3b. With command 39 still pending, it returns while remaining at 0x3a. No public-version or component-flag comparison appears in this bounded completion transition.
- State 0x3b reads handshake byte `0x20390308`. With zero, it returns without advancing or writing a command. With one, it reaches the main-update producer 0x20022fc0. Execution stops there; command 11 is not injected or written by this probe.

The main-update producer is therefore gated locally on handshake value 1, not directly on public Main CPU version or the three component-change flags. This does NOT rule out version/equality gating upstream: normal creation of UI states, interpretation of the two state-0x39 predicates, and production of handshake value 1 remain unproven.

## Exact next bounded experiment

Resolve `0x20047f08` and `0x2000a23c` as used by `0x20059060`, and trace the writer that establishes `0x20390308 == 1` before state 0x3b. Keep this restricted to the update-screen path and its original data sources; do not broadly classify every UI callback or treat a seeded handshake as user confirmation. Determine whether these values derive from explicit confirmation, readiness, or version/component eligibility before claiming matching-version input can reach command 11 normally.

Same-version reinstall and custom-to-stock restoration remain unproven. Existing component equality acceptance is still only stage-local evidence. No exact candidate, installation decision, failed-boot recovery or TX authorization follows.
