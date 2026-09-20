# Security and safety policy

## Supported status

The project is currently research software. It is not installable radio firmware
and must not be treated as a production radio-control system.

## Reporting a vulnerability or safety concern

Use GitHub's private vulnerability-reporting feature if available. Otherwise,
contact the maintainers privately. Do not disclose exploitable updater details,
vendor firmware, credentials, recordings, station data, or a ready-to-flash
image in a public issue.

Include the affected source revision, target radio/official base firmware,
reproduction steps, observed behavior, and whether RF transmission was involved.

## Disclosure and remediation

Maintainers will acknowledge a report, assess safety impact before reproduction,
and coordinate a fix or mitigation before public disclosure where practical.

## Operational boundary

Any future hardware test requires an explicit written test plan, a validated
recovery path, an immediate operator stop control, and independent verification
appropriate to the test phase. Transmission is out of scope until the dedicated
TX-safety work has been completed and reviewed.
