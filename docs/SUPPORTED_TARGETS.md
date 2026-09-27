# Supported target matrix

## Current development target

| Field | Value |
| --- | --- |
| Radio | Original Icom IC-7300 only |
| Hardware status | Owner completed official 1.41 → 1.42 SD update; no custom image flashed |
| Initial research base | Official IC-7300 Main CPU firmware 1.42, `7300_142.dat` |
| Base image SHA-256 | `8cf5324a126f105cd2307c30b191b9dd8183f86b2c8bf229e61bf9a6a8c32f32` |
| Other observed base images | 1.40 and 1.41, research/comparison only |
| Geographic variants | Not yet qualified |
| IC-7300MK2 | Explicitly unsupported and excluded |

The base image hash is an identification value, not a distribution source.
Users must obtain an official image themselves. The repository must not contain
the image or any extracted vendor payload.

## Compatibility rules

The shared registry in `research/targets.json` authorizes exact image hashes for
offline firmware commands. Analysis, extraction, comparison and lossless
reconstruction accept pinned 1.40, 1.41 and 1.42 images; only 1.42 is the
development base. Version-specific tracing accepts only the pinned 1.42 source
and decoded application. Filenames and extraction manifests cannot authorize
unknown bytes. Acquisition metadata updates do not extend this registry.

Commands fail closed for unknown or altered images, including unregistered
regional and IC-7300MK2 images. Recognizing a research image does not qualify any
regional radio for installation. Adding a target
requires a separately reviewed issue covering provenance, image format, recovery
evidence, safety tests, and legal/distribution impact.

## Present scope

The owner’s version screen now shows official 1.42 after a normal SD update.
This confirms the stock update path on that radio, not flash readback, regional
qualification or failed-application recovery. Firmware 1.42 remains the research
base; there is no supported custom install image or proven recovery procedure.
Real-image packing stays disabled and TX is not authorized. Region-specific compatibility and operator rules remain open work.
