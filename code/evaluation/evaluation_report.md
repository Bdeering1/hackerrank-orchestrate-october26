# Evaluation report

## Results

Final scores on commit `1c1ab68`, from `uv run python -m evaluation.main` (default suite) and
`--holdout`. The default suite is the 32 public samples plus the 6 custom cases, minus the 5
holdout cases: 33 cases. The scorer is `evaluation/score.py`. Step, field and sequence scores
pool every step across cases.

| Metric | Weight | Definition | Default (33) | Holdout (5) |
| --- | ---: | --- | ---: | ---: |
| Status | 25% | Exact `deletion_status` match, averaged over cases | 100.0% (33/33) | 100.0% (5/5) |
| Step | 35% | Multiset F1 over steps, ignoring `step_no` | 94.4% | 100.0% |
| Field | 30% | `operation`, `state` and `evidence_id` agreement on steps aligned by phase, system and resource | 91.5% | 100.0% |
| Sequence | 10% | 1 minus summed step edit distance over summed longer list length | 90.8% | 100.0% |
| **Composite** | | Weighted sum | **94.6%** | **100.0%** |

The full 518-case run passes `evaluation.main validate`: 153 `COMPLETE`, 352 `INCOMPLETE`
and 13 `NOT_APPLICABLE`.

### Cases below 100%

Every status is right. Except in case_07, every miss is a missing step; the agent adds no wrong step.

| Case | Composite | Missing steps | Cause |
| --- | ---: | --- | --- |
| case_03, case_21, case_25, case_26, case_27 | 79.7-90.2% | One analytics `VERIFY_RECORD_ANONYMIZED` | The anonymized profile carries no identifier, so nothing links it to the subject |
| case_28 | 79.7% | Analytics `VERIFY_RECORD_ANONYMIZED` and account `VERIFY_RECORD_ABSENT` | Both records are unlinked, as above |
| case_04, case_23, case_29, case_31, case_32 | 68.3-95.8% | One account `VERIFY_RECORD_ABSENT` | No evidence file or activity row links the deleted account to the subject |
| case_18, case_20 | 92.7-95.8% | One security `VERIFY_RECORD_PRESENT` | The record appears in no text evidence file, and extraction did not recover it (inferred PDF or screenshot only) |
| case_07 | 53.8% | `support_001` delete steps, replaced by redact steps | Extraction labels the attachment PDF as a support message, so the REDACT rule applies instead of DELETE |

## Custom evaluation cases

Six custom cases add to the 32 public samples. Requests are in `cases/custom_requests.csv` and
expected answers in `cases/custom_output.csv`. All of them use only the existing dataset. The
full per-case reasoning, with the evidence IDs behind each label, is in
[cases/README.md](cases/README.md).

| Case ID | Derived from | What it tests | Expected status | Holdout |
| --- | --- | --- | --- | --- |
| case_901 | case_01 | Access/export request that says not to delete, sent with a `COMPLETE` workflow claim | NOT_APPLICABLE | no |
| case_902 | case_02 | Spanish marketing opt-out that uses the verb "delete" | NOT_APPLICABLE | yes |
| case_903 | case_10 | Request from an intermediate historical email: identity history has to be followed both ways | INCOMPLETE | no |
| case_904 | case_08 | Same request rewritten in Portuguese | INCOMPLETE | no |
| case_905 | from scratch (user_531) | Deletion after an earlier non-deletion request, with an account still present, a retained security record and a similar-name decoy | INCOMPLETE | yes |
| case_906 | from scratch (user_538) | Uppercase request email, Swedish text, unsupported `COMPLETE` claim, account still present | INCOMPLETE | no |

The holdout suite (`cases/holdout.txt`) is samples case_02, case_12 and case_30 plus case_902
and case_905. Holdout cases are left out of default runs and promotion and are never used as
prompt examples. `uv run python -m evaluation.main --holdout` scores them and compares the
result with the previous holdout run.

case_02 replaced case_04 after a nomination rule was derived from diagnosing case_04, which
made its holdout score a tuned result. Holdout scores from before the swap are not comparable
with later ones. [cases/README.md](cases/README.md) explains the choice.

## Failures found and improvements made

Most categories were built on parallel branches from one base, which scored 13.9% on the
default suite. Scores below are from each pull request, measured against that base unless
noted.

| Change | Failure it addressed | Default composite |
| --- | --- | --- |
| Account audit end to end | Placeholder agent produced no steps | 0% -> 10.6% (5/32 statuses) |
| Account nomination from deletion-worker claims | Accounts with no identifier link were never audited | 13.9% -> 20.2% |
| Retained records and account tombstones | Security and legal-hold records got no `VERIFY_RECORD_PRESENT`, and tombstones were never checked for exposed PII | 13.9% -> 26.8% |
| Support redaction and analytics anonymization | Every non-delete record was treated as a delete | 13.9% -> 37.7% |
| Data flows and restore risks | Active connectors and restorable backups were ignored | 13.9% -> 38.3% |
| Search, export and attachment deletions | Three categories had no module | 13.9% -> 44.9% |
| PDF and screenshot extraction | Records shown only in documents and screens never reached the audit | 92.6% -> 93.6% (old holdout split) |
| Uncited retained records, targeted analytics nomination | See below | 91.2% -> 93.6%; holdout 97.6% -> 100% |

Failures found along the way, and the fixes:

- **Partial snapshots proved absence.** A 5-user bundle extract timed at `audit_at` omitted a
  search entry that a log showed present (case_19, `search_6083`). A bundle now proves a
  record absent only when an earlier snapshot of the same copy listed it.
- **Omission flipped retained records to gaps.** Replica and later primary snapshots often
  leave out retained support and analytics records, which flipped cases 19 and 26-28. Only
  DELETE rules now treat omission as absence. An earlier version that kept the omission rule
  peaked at 31.5% but was right for the wrong reasons, so it was dropped.
- **Omission hid active flows and backups.** Treating a connector or backup missing from a
  bundle as gone turned cases 15 and 17 `COMPLETE`. Omission never proves these absent.
- **Earlier requests leaked in.** Resources linked during the subject's previous deletion
  request were audited again (sample case_17 against eval case_46). Links older than the
  previous request's audit are now dropped.
- **Retained records seen only in later files were dropped.** A bundle exported after
  `audit_at` was the only evidence for some security records. They now get an uncited
  `VERIFY_RECORD_PRESENT` in `INCOMPLETE` cases (cases 09, 23, 24, 29, 30).
- **Untargeted analytics nomination took the wrong record.** Paired sample cases share
  `reported_at`, so a time window nominated the other case's record (91.9%). Nomination now
  uses only claims that name a target resource.
- **Holdout contamination.** The targeted-nomination rule came from diagnosing holdout
  case_04, so case_02 replaced it in the holdout. Holdout scores from before the swap are not
  comparable.
- **Validator conflict.** A deletion with no linked resource cannot be `COMPLETE` with no
  steps, so it is `NOT_APPLICABLE`.
