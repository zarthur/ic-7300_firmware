# Same-version stock restoration: bounded acceptance finding

Baseline: `e4dfee35c63b5eeb1e6e5dfbd066ab47318355ac`, official v1.42 image SHA-256 `8cf5324a126f105cd2307c30b191b9dd8183f86b2c8bf229e61bf9a6a8c32f32`. Reproduction: `tools/update_dispatch.py` with the locally retained official image. All original image bytes remained unchanged. Only synthetic installed-identifier RAM values and dispatcher command state were supplied. No device I/O or firmware edits.

## Conclusion

The recovered header precheck does not reject equality of its three component identifiers. Equality yields success and three zero component-change flags. This is evidence against an equality rejection *at that stage*, not proof that the normal update menu permits a same-Main-CPU-version reinstall. These identifiers are not the public Main CPU version, and live state/UI command progression is not established.

Six executions of original header precheck `0x200253f4`:

| Supplied installed component identifiers | Result | Component-change flags |
| --- | --- | --- |
| All equal to the unchanged official file header | Accepted | 0,0,0 |
| All synthetic numeric 0.00 | Accepted | 1,1,1 |
| All synthetic numeric 9.99 | Accepted | 1,1,1 |
| Only identifier 0 changed | Accepted | 1,0,0 |
| Only identifier 1 changed | Accepted | 0,1,0 |
| Only identifier 2 changed | Accepted | 0,0,1 |

The numeric stimuli show no lower/higher version rejection in these tested comparisons; do not interpret them as approved downgrade tests. The actual bytes differ, rather than a public-version ordering being exercised. File services, comparison helper and RAM identity provisioning remain explicit existing harness models.

Separately, the original payload checker with flags 0,0,0 accepts the same official image, computes exactly one payload MD5 (main), and skips nonselected component payload validation. It reads 2,436,112 bytes through the modeled file API. This supports a main payload validation route even when all three component identifiers match; it does not execute non-main update handlers or authorize skipping their safety analysis.

## New boundary: checks are separately dispatched, not a proven uninterrupted chain

A bounded ARM direct-call scan found these reviewed direct-call sites:

- `0x2002765c` calls header precheck `0x200253f4`.
- `0x20027664` calls payload precheck `0x20025650`.
- `0x2002766c` calls main update `0x20025ae4`.

They belong to a command switch rather than consecutive execution of all three stages. Executing only the original dispatch selection at `0x2002754c`, with a synthetic context command at offset +0x44, reaches respectively command 38 -> header precheck, command 39 -> payload precheck, command 11 -> main update. Each takes five original dispatch instructions before reaching the callee. Execution stops at the callee; no invented task/queue model supplies event progression.

This prevents a misleading inference: independently successful checks do not prove that stock UI/task logic issues the main-update command for same-version input. The omitted producer may impose additional eligibility or confirmation conditions. The bounded direct-call scan is not a complete inventory of mixed-ISA/computed callers.

## Exact next question

Trace the producers/eligibility logic for the command field +0x44 (commands 38,39,11), beginning with task context initialization and update UI actions. Bound the work to establishing whether a public Main CPU version comparison or all-components-unchanged condition prevents command 11 after successful checks. Record unknown helpers and do not inject a main-update command then call that end-to-end acceptance. Existing filename enumeration at `0x20025300` and live menu selection remain separate prerequisites; no force option or undocumented recovery command is supported.

## Decision impact

Software-restoration documentation can now say: matching component identifiers are accepted by the recovered header checker and main payload validation still runs, but normal same-version update selection/dispatch is unresolved. Stock 1.41 -> 1.42 upgrade remains the only observed hardware installation. Same-version reinstall, custom-to-stock restoration, failed-boot recovery, current backup coverage and physical write completion remain unproven. Keep the later exact-candidate owner decision and software-only scope unchanged.
