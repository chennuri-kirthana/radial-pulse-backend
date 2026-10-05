"""The version of the API contract (openapi/openapi.json) that this code serves.

Bump it in the same pull request that changes the contract, and add a line to
openapi/CHANGELOG.md. Rules (docs/api/contract-versioning.md):

* 0.x.y while we are before the first production launch:
  - y (patch): fixes and additions that cannot break a screen (new optional field, new route)
  - x (minor): anything that can break a screen (removed/renamed field or route, new required
    input, changed meaning)
* from 1.0.0 on: normal semantic versioning (major = breaking).

A git tag vX.Y.Z publishes this exact contract as a GitHub Release (.github/workflows/release.yml);
the release fails if the tag and CONTRACT_VERSION differ.
"""

from __future__ import annotations

CONTRACT_VERSION = "0.2.0"
