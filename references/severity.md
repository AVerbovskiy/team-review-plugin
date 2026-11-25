# Severity scale

Two independent axes: **severity** (how bad if real) and **confidence** (how sure we are it is real).

| Level | Icon | Meaning | Blocks merge | Typical examples |
|---|---|---|---|---|
| `blocker` | 🔴 | Will break production, lose or corrupt data, open a security hole, or violate an accepted ADR | Yes | IDOR on an account endpoint, money computed in floating point, a migration that locks a hot table, PII in logs, ignoring an accepted ADR |
| `major` | 🟠 | Likely bug in a realistic case, a missing ticket requirement, or a structural problem that is costly to fix later | Usually | An unhandled DST boundary, a non-idempotent consumer, an AC not implemented, domain logic in the controller, no test for the main path |
| `question` | ❓ | The reviewer cannot judge without the author's knowledge | Until answered | "Is this endpoint meant to be public?", "Is the scope change agreed with the PO?" |
| `minor` | 🟡 | Maintainability, a missing test for a secondary path, unclear naming, a small convention deviation | No | Duplicated helper, a magic number, an untested error branch |
| `nit` | 🔵 | Taste and polish | No (hidden by default) | Wording of a log message, ordering of imports |

Confidence:

| Level | Meaning | Shown by default |
|---|---|---|
| `high` | Verified in code; a concrete scenario exists | Yes |
| `medium` | Very likely; depends on something not fully confirmed | Yes |
| `low` | Suspicion worth a look | No (`--all`) |

Rules of thumb:
- If you are unsure between two levels, choose the lower one and lower the confidence. Do not inflate.
- Security and data-loss issues are rated by realistic impact, not by how theoretical the attack is.
  But a theoretical issue gets `low` or `medium` confidence.
- A pre-existing problem is reported only when this diff touches the code and the problem is `major` or above.
  It is labelled "pre-existing".

Verdicts: `changes_required` (any blocker) → `needs_discussion` (major or question) → `approve_with_comments` (only minor or nit) → `ready`.
