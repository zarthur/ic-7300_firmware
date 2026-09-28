# UI eligibility predicate and handshake writer: bounded follow-up

Source: `f8ac12f23ce11b8858969e41d8a9a00943a692cf`, exact pinned official v1.42 image. Reproduce the ten predicate cases with `tools/update_dispatch.py`. No device I/O or image mutations.

## Predicate semantics now executed

The state-0x39 predicate `0x20059090` tail-calls `0x20059060`. The latter executes the following original routines without replacing their return values: `0x20047f08`, `0x2006a3f4`, `0x2006be8c`, and `0x2000a23c`.

Its Boolean result is 1 exactly when the following modeled RAM conditions all hold:

- Unsigned bytes at `0x203902a2`, `0x2039027f`, `0x20390285`, `0x203da3d0`, and `0x20396ac8` are zero.
- Signed bytes at `0x20390448` and `0x20390449` are <= 0. Their sign matters: 0xff is -1 and does not inhibit this predicate.

The first routine `0x20047f08` checks four unsigned conditions and the two signed conditions; `0x2000a23c` returns the remaining unsigned byte at `0x20396ac8`. Ten bounded original-instruction runs passed: all-zero accepts; making each of seven inputs +1 individually rejects; making either signed input -1 individually accepts. Every run returned within 300 instructions and one second. No predicate helper was stubbed, and no command was submitted.

These are concrete byte predicates, not identified user-action meanings. No public Main CPU version or component-change identifier is read in these executed routines. Accordingly, there is no direct same-version or all-identifiers-equal rejection here. Upstream setters can still depend on unexamined state, and successful synthetic inputs do not prove normal update-screen entry.

## Handshake value 1 has an identified original writer

The exact-pointer search and bounded literal-load inspection locate the handshake store at `0x2002b6b0` to `0x20390308`, using R8. The enclosing function begins `0x2002b580`; an earlier instruction at `0x2002b5cc` sets R8 to 1. This is a static writer relationship, not a complete execution of the containing task. Numerous intervening calls remain unexecuted; preserving R8 across them follows the apparent ABI, not a demonstrated whole-path run.

Immediately preceding the writer, the reviewed path:

1. Checks a separate byte and loops back to `0x2002b5e8` when nonzero.
2. Requires the same original `0x20047f08` readiness predicate to return nonzero.
3. Calls `0x20061098`; if nonzero, additionally requires a byte at caller context +0x0e to be at least 0xfa.
4. Optionally runs `0x200604c4` between interrupt-mask operations, then calls `0x200b60dc`.
5. Stores R8 to the handshake at `0x2002b6b0`, then calls `0x2007f198`.

The old UI seed of handshake=1 therefore has a specific producer to investigate. It is not established as a confirmation button, an update-only handshake, or a normal same-version path. The related original store at `0x2002b39c` is in an earlier function where R8 is initialized to zero, consistent with a reset path but likewise not fully executed. The existing UI state-0x3c store of 1 is a later path and does not by itself explain initial eligibility.

## Decision impact and next exact boundary

The two formerly unknown payload predicates are now resolved to seven RAM conditions, none directly reading version/component identifiers. Same-version eligibility remains unproven because normal origins of these fields and the handshake-producing path are not established. This narrows the missing evidence; it does not justify disabling guards or assuming user confirmation.

Next bound the original path `0x2002b658..0x2002b6b4`, beginning with the meaning/source of its separate byte gate and the return of `0x20061098`. Stop before unqualified interrupt/device helpers `0x200604c4` and `0x200b60dc` rather than fabricating completion. Separately identify the caller/context establishing the update UI state; no need to repeat the seven-predicate Boolean study or rescan all command writers.

No same-version reinstall, custom-to-stock restoration, failed-boot recovery, candidate construction, installation approval or TX authorization is established.
