# Legal and distribution policy

This project is an independent, non-commercial research effort and is not
affiliated with, endorsed by, or supported by Icom Incorporated.

## What this repository may contain

- Original source code, tests, documentation, measurements, hashes, and
  independently written analysis.
- Instructions that require each user to obtain a supported official firmware
  image directly from Icom.
- A local tool which verifies a user-supplied base-image hash before operating.

## What must not be committed or released

- Icom firmware archives, `.dat` images, extracted/decompressed sections,
  disassembly listings containing substantial vendor code, or derived images.
- Vendor artwork, fonts, icons, manuals, recordings, or strings beyond what is
  necessary for short factual identification or compatibility documentation.
- Credentials, radio settings backups, call-sign logs, recordings, or personal
  data.

No release may provide a ready-to-flash image. Any future local patching process
must preserve this boundary, identify its exact supported base-image hash, and
be reviewed for applicable copyright, contract, anti-circumvention, export, and
radio-regulatory requirements before publication.

Reverse engineering and modification rules vary by jurisdiction. In the United
States, the interoperability provision in 17 U.S.C. 1201(f) is limited and does
not itself authorize infringement, distribution of all circumvention tools, or
violation of other law. Contributors and users are responsible for obtaining
their own legal advice where needed.

Third-party code may be used only with a documented compatible license and
required notices. See `THIRD_PARTY_NOTICES.md`.

## US project context

The owner is a licensed US radio amateur. Equipment experimentation must still
respect license privileges and emission requirements; the operator remains
responsible for compliant transmissions ([47 CFR 97.105](https://www.law.cornell.edu/cfr/text/47/97.105),
[97.307](https://www.law.cornell.edu/cfr/text/47/97.307)).
Radio ownership does not itself grant unrestricted firmware rights: copyright
law reserves reproduction, adaptation and distribution rights, with limited
exceptions for owners of software copies ([17 USC 106](https://www.law.cornell.edu/uscode/text/17/106),
[117](https://www.law.cornell.edu/uscode/text/17/117)).
The interoperability exception in [17 USC 1201(f)](https://www.law.cornell.edu/uscode/text/17/1201)
is conditional, not blanket permission to bypass protections or distribute bypass
tools. Current research identifies compression and checksums; it has not
established circumvention of a legally relevant access control. Applicable Icom
license terms and any future protection bypass require assessment on their facts.

This is a high-level orientation, not a legal opinion. Qualified review under
issue #8 remains outstanding before publishing future patching/circumvention
tools; it does not block the current offline target-validation work.

## Reporting concerns

Please open a private security report through GitHub for accidental inclusion of
vendor material, credentials, unsafe behavior, or a suspected vulnerability.
Do not attach proprietary firmware or radio captures to a public issue.
