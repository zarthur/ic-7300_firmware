# Supported target matrix

## Current development target

| Field | Value |
| --- | --- |
| Radio | Original Icom IC-7300 only |
| Hardware status | No hardware image has been modified, flashed, or tested |
| Initial research base | Official IC-7300 Main CPU firmware 1.42, `7300_142.dat` |
| Base image SHA-256 | `8cf5324a126f105cd2307c30b191b9dd8183f86b2c8bf229e61bf9a6a8c32f32` |
| Other observed base images | 1.40 and 1.41, research/comparison only |
| Geographic variants | Not yet qualified |
| IC-7300MK2 | Explicitly unsupported and excluded |

The base image hash is an identification value, not a distribution source.
Users must obtain an official image themselves. The repository must not contain
the image or any extracted vendor payload.

## Compatibility rules

No future image-aware tool may process a file merely because its name appears to
match. It must require an exact supported model/version/hash entry and fail
closed for every unknown, altered, regional, or IC-7300MK2 image. Adding a target
requires a separately reviewed issue covering provenance, image format, recovery
evidence, safety tests, and legal/distribution impact.

## Present scope

Firmware 1.42 is an analysis target only. It is not a supported install target,
and there is no flash-ready image, packer, recovery procedure, or permission to
transmit. Region-specific compatibility and operator rules remain open work.
