# Owner-observed official update — 2026-09-20

The owner's original IC-7300 displayed Main CPU 1.41 in `IMG_2676.jpeg` and
Main CPU 1.42 in `IMG_2677.jpeg`, supplied in the project conversation. Both
photos show Front CPU 1.01, DSP Program 1.07, DSP Data 1.00 and FPGA 1.13.
The photos remain local; no device photograph or private station data is copied
into the repository.

Before the update, read-only inspection of the owner's SD card found
`7300_142.dat` at the root instead of inside `IC-7300/`. Its length was 3,954,089
bytes and SHA-256 was
`8cf5324a126f105cd2307c30b191b9dd8183f86b2c8bf229e61bf9a6a8c32f32`, matching the
pinned official image. The owner corrected the location and reported success,
supplying the post-update version-screen photo. The agent did not write the
card, operate the updater or issue radio commands.

Two settings files of 8,224 bytes were present before the update. Their presence
was observed, but contents, coverage and restoration were not validated.

Established: the radio can use the normal official SD update path and subsequently
display the version screen reporting 1.42. This is useful target qualification
for continuing offline 1.42 research.

Not established: complete flash readback, physical active-bank contents, normal
receive regression results, calibration/settings restoration, regional/board
qualification, or recovery when the main application cannot boot. The stock
update does not close #11 or authorize a modified-image boot.
