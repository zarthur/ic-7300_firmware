# Handshake preconditions: bounded final UI increment

Baseline `961c50e61095b3680d20a1c768daa5aaa13928b2`; unchanged pinned original v1.42 image SHA-256 `8cf5324a126f105cd2307c30b191b9dd8183f86b2c8bf229e61bf9a6a8c32f32`. The bounded original-code probe and results are retained locally under `artifacts/decision-review-20260928T0808/`. No repository edits, device I/O or image changes.

## Concrete newly executed semantics

The separate byte gate at the start of `0x2002b658` reads `0x203903f0`. Nonzero branches back to the surrounding loop at `0x2002b5e8`; zero proceeds to the previously recovered readiness predicate `0x20047f08`. No public-version comparison occurs at this gate. The live semantic name and writer of this byte remain unqualified.

The original helper `0x20061098` returns the Boolean OR of six nonzero-byte tests:

- `0x203fc57a`
- `0x203fc57b`
- `0x203fc59c`
- `0x203fc597`
- `0x203fc599`
- `0x203df205`

It executes its subordinate getters `0x20061054` and `0x20061070` directly. All-zero input returns 0. Individually setting any one of these bytes to 1 returns 1. No helper return is substituted.

At its call site, return 0 bypasses the next byte-threshold condition. Return 1 requires the unsigned byte at caller context +0x0e (`0x203fc62d` with the statically identified context) to be >= 0xfa. A value of 249 loops; 250 proceeds. This is a byte threshold, not an established duration or proof that a timer has elapsed.

The next optional flag is `0x2039038c`. Nonzero leads to an interrupt-mask instruction and helper `0x200604c4`; zero skips that branch. Both paths subsequently encounter `0x200b60dc`, before the known handshake store at `0x2002b6b0`.

## Thirteen bounded executions

Seven helper runs establish the all-zero and six single-nonzero cases. Six call-site runs establish:

| Modeled stimulus | Observed stopping point |
| --- | --- |
| Separate gate nonzero | Loop boundary 0x2002b5e8 |
| Readiness predicate inhibited | Loop boundary 0x2002b5e8 |
| Six helper flags zero, threshold byte zero | Unexecuted helper 0x200b60dc |
| One helper flag nonzero, threshold byte 249 | Loop boundary 0x2002b5e8 |
| One helper flag nonzero, threshold byte 250 | Unexecuted helper 0x200b60dc |
| Optional flag nonzero, other predicates clear | Before interrupt-mask instruction 0x2002b69c |

Each case is bounded to 500 instructions and one second. The original relevant predicate instructions execute; RAM fields and context registers are explicitly seeded. Execution stops before the loop body, interrupt masking or unknown helper. All cases leave the handshake byte zero. No normal user action, task entry, interrupt effects, device-helper completion or actual handshake transition is fabricated.

## Relevance to same-version stock restoration

These conditions add no direct public-version or all-components-unchanged comparison to the local path. Together with matching component identifiers being accepted by the earlier header checker, this supports keeping ordinary same-version restoration as a conditional proposal rather than asserting a discovered version rejection. It does not demonstrate that the working stock UI will complete a reinstall or that a custom image can be restored.

For the owner decision package, say exactly that normal UI acceptance and successful return-to-stock remain untested; current evidence does not identify a same-version rejection in the examined routines. This uncertainty can be disclosed alongside the exact candidate and proposed official procedure. It need not become a demand to simulate every unrelated task or interrupt implementation before continuing offline preparation.

## Precise remaining boundary

The next physical/task-effect boundary is `0x200b60dc`, plus the optional interrupt-protected `0x200604c4` path and origins of the modeled readiness bytes. Their successful completion was not supplied. Leave them unknown rather than rerunning the Boolean and threshold studies. Any later live same-version confirmation requires its own explicit owner authorization; this report authorizes no installation, recovery experiment, or TX.
