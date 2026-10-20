# Security policy

English · [한국어](SECURITY.ko.md)

## Reporting

Use the repository's **Security → Report a vulnerability** private reporting route.
Include affected versions, prerequisites, synthetic reproduction steps and impact.
Do not publish exploit details or send real credentials in issues.
If private reporting is unavailable, wait for a private route rather than posting
sensitive material publicly.

This is a development preview with no response-time or long-term-support commitment.
Fixes target current development and the latest preview. Dependency advisory checks
describe the checked environment, not a security guarantee.

## Using Duru

Inject credentials from your application; keep tokens and private files outside Git.
Use content revisions with checked reads and conditional writes.
An EffectUnknown result means a mutation may already have happened: reconcile before retrying.

Local filesystem confinement is hardened on Linux. Windows uses checked paths and
does not provide the same descriptor-based confinement guarantees.
Local mutation locks coordinate cooperating clients, not unrelated OS writers.
Buffering checked file contents uses memory proportional to file size.

Galmuri account policies, document permissions, scheduling, and indexing belong to
applications using Duru, not to this library.
