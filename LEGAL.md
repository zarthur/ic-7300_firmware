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

## Reporting concerns

Please open a private security report through GitHub for accidental inclusion of
vendor material, credentials, unsafe behavior, or a suspected vulnerability.
Do not attach proprietary firmware or radio captures to a public issue.
