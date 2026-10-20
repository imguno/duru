# Release procedure

English · [한국어](RELEASE.ko.md)

## Before a release

1. Update the package version and prepare GitHub Release notes.
2. Run local checks and inspect the staged/public files for private material.
3. Run distribution verification from a clean source snapshot. Validate both the
   wheel and sdist, their source payloads, and the independently installed API.
4. Confirm the current commit's CI results, dependency audit and independent review.
5. Configure the protected GitHub environment `pypi` and the corresponding PyPI
   Trusted Publisher. Do not put a PyPI API token in repository secrets.

A main-branch push runs CI only. Publishing starts on a **published GitHub Release**.
Use an exact version tag, for example `v0.1.0` for package version `0.1.0`.
The release workflow checks the tag/version, runs CI, rebuilds and validates distributions,
then the separate `pypi` environment job publishes using GitHub OIDC.
Previously published versions are not overwritten.

## Initial registry setup

In PyPI, configure a pending/trusted publisher using the actual GitHub owner,
repository, workflow `publish.yml`, and environment `pypi`.
For Duru the owner is `imguno` and the repository is `duru`.
Account verification and any required 2FA are managed on PyPI.

Release **Duru first**, confirm `pip install duru==VERSION` from PyPI in a clean
environment, then release Galmuri against that available dependency.
Registry publication requires PyPI-side setup; committing a workflow is not a publish.

## Installation verification and rollback

Use a fresh virtual environment to install the exact published version. Run
`python -m pip check` and the Duru README examples, including resource reads
and conditional writes.
Verify the package comes from the intended project, not an older local checkout.

If a release is broken, stop further releases and investigate. Publish a new version
rather than trying to overwrite files. PyPI yanking is a separate maintainer action.
Before upgrading an application, check provider capabilities and revision behavior
against its storage service. A package downgrade cannot undo remote resource writes.

Run `python tools/release.py --output .verification/release` from this checkout to
verify Duru's own source and wheel distributions, dependency-free installation,
resource reads and conditional writes. Galmuri's CLI and skill belong to its own release.
