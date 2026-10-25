# Custom evaluation cases

`custom_requests.csv` holds extra requests in the dataset request format and `custom_output.csv`
their expected answers. Every label below was derived by hand from participant-facing files
under `dataset/` only. No new evidence was created.

The harness scores samples and custom cases together. Run from `code/`:

```text
uv run python -m evaluation.main              # default suite: every case not in holdout.txt
uv run python -m evaluation.main --holdout    # holdout suite only, compared with the previous holdout run
uv run python -m evaluation.main [--holdout] --predictions <output.csv>
```

## Holdout rule

`holdout.txt` lists the holdout cases: `case_02`, `case_12`, `case_30`, `case_902` and
`case_905`. They are left out of default runs and promotion, and they must never be used as
prompt examples or few-shot material. `tests/test_cases.py` fails if a holdout request text
appears in any file under `ghost_audit/`.

`case_02` replaced `case_04` on 2026-10-25. The targeted analytics nomination rule was found
by diagnosing `case_04`, the only case in the dataset it affects, so `case_04` no longer
measures unseen behaviour and now runs in the default suite. `case_02` is the only `COMPLETE`
sample that no change was diagnosed from and no default custom case was derived from. Its
variant `case_902` was already held out, so subject user_02 is now entirely in the holdout. Like
every sample, `case_02` had scored in earlier default runs, so it is the least-exposed choice,
not an unseen one.

## Cases

### case_901: access request (variant of case_01)

- Same subject (`amina.elmasri@gmail.com`, user_01), timestamps and `reported_status`
  (`COMPLETE`) as case_01.
- The text asks for a downloadable copy of the personal data and says "Do not close or delete
  anything yet". This is an access/export request, so it does not authorize deletion (AGENTS.md
  §6.5).
- Expected: `NOT_APPLICABLE`, `[]`. The reported `COMPLETE` status and the subject's real
  deletion history are distractors.

### case_902: marketing opt-out in Spanish (variant of case_02, holdout)

- Same subject (`mateo.rios@outlook.com`, user_02), timestamps and `reported_status`
  (`PARTIALLY_COMPLETE`) as case_02.
- The text asks to stop promotional email and be removed ("bórrenme") from marketing lists, and
  to keep the account and order history. A marketing opt-out is not a deletion request (§6.5),
  even though it uses the verb "delete".
- Expected: `NOT_APPLICABLE`, `[]`.

### case_903: request from an intermediate historical email (variant of case_10)

- case_10 is sent from `nadia.ionescu@yahoo.com`. user_10's email changed to
  `nadia.petrescu@yahoo.com` at `audit_121` (2025-12-13) and then to `n.petrescu@yahoo.com` at
  `audit_238` (2026-04-12). This variant is sent from `nadia.petrescu@yahoo.com`, an address that
  was already historical at `requested_at` (2026-08-31). The request text and timestamps match
  case_10.
- The agent has to follow the history in both directions. `evidence_61` (support replica log,
  2026-09-17) still finds `support_002` under the oldest address `nadia.ionescu@yahoo.com`, and
  reports `marker_found=false` even though `activity_3596` claimed `SUCCESS`. Rule_06 requires
  DELETE. `support_5914` in the same log belongs to `nadia.popescu@yahoo.com`, a different
  person.
- `account_010` is absent: `activity_3595` reports the deletion and the 2026-09-02 failover
  snapshot (`evidence_54`) no longer lists it.
- Expected: same as case_10. `INCOMPLETE`: report `support_002` (`evidence_61`), delete it,
  verify `account_010` and `support_002` absent.

### case_904: request in Portuguese (variant of case_08)

- Same subject (`gabriel.costa@proton.me`, user_08) and timestamps as case_08. The text is a
  Portuguese rewrite of case_08: the account is closed, but an old "download your data" link
  still works.
- `evidence_59` (export jobs, 2026-09-14T15:40, before audit_at 16:10) shows `export_001`
  owned by `gabriel.costa@proton.me` with `download_available: true`. `activity_3555` reports
  the deletion as `FAILED`. Rule_09 requires DELETE. `account_008` was deleted
  (`activity_3554`).
- Expected: same as case_08. `INCOMPLETE`: report `export_001` (`evidence_59`), delete it,
  verify `account_008` and `export_001` absent.

### case_905: new deletion after a non-deletion request (from scratch, holdout)

- Subject: user_531 Haruka Kato, `haruka-kato@gmail.com`. In the evaluation set she sent only a
  phone-number correction (case_533), and `activity_3789` (2026-09-11) records that request for
  `account_1733` as non-deletion. This custom request is a real deletion request sent afterwards:
  requested 2026-09-28, reported `NOT_STARTED`, audit_at 2026-10-02T09:00.
- `evidence_50` (security audit ledger, captured 2026-10-01T12:00, before audit_at) lists
  `account_1733` (`USER_PROFILE`, `FOUND`, subject `haruka-kato@gmail.com`) and
  `audit_record_7626` (`SECURITY_AUDIT_LOG`, `FOUND`, subject `user_531`). No activity deletes
  either record.
- Policy: rule_01 requires the profile to be deleted. Rule_12 retains the security audit
  record, so following the samples (case_16, case_24) it gets a `VERIFY_RECORD_PRESENT` step but
  no finding.
- Decoy: `evidence_04` (account admin console, 2026-09-26) shows Haruka **Sato**, user_11,
  `account_5762`, `haruka.s1838@zoho.com`, a different person.
- Expected: `INCOMPLETE`: report `account_1733` remaining (`evidence_50`), delete it, verify
  `account_1733` absent and `audit_record_7626` present. The step layout follows case_16.

### case_906: uppercase email, Swedish, false COMPLETE claim (from scratch)

- Subject: user_538 Ingrid Eriksen, `ieriksen5151@fastmail.com`. In the evaluation set she only
  asked for invoices (case_540), and `activity_3512` records that request for `account_2176` as
  non-deletion. This custom request is sent from `IERIKSEN5151@FASTMAIL.COM` (identity matching
  has to ignore case, as some evaluation requests do) and is written in Swedish. It allows
  security logs to be kept. It is reported `COMPLETE` on 2026-09-29, with audit_at
  2026-10-02T10:00.
- No deletion activity exists for `account_2176`, so the `COMPLETE` claim is unsupported.
  `evidence_50` (2026-10-01T12:00) still lists `account_2176` (`USER_PROFILE`, `FOUND`, subject
  `ieriksen5151@fastmail.com`) and `audit_record_7894` (`SECURITY_AUDIT_LOG`, `FOUND`, subject
  `user_538`).
- Expected: `INCOMPLETE`: report `account_2176` remaining (`evidence_50`), delete it, verify
  `account_2176` absent and `audit_record_7894` present.

## Confidence notes

- In case_905 and case_906, the security audit records come with no `retention_until`. They are
  treated as within retention because every sample with a subject-linked `audit_record_*`
  verifies it as present.
- Neither from-scratch subject's email, name, phone or email hash appears in any other
  text-searchable evidence file (checked with `rg`). All four PDFs were read and concern other
  users. Each screenshot was captured within an hour of a data-catalog `LINK_RESOURCE_IDENTITY`
  activity (`activity_4000` to `activity_4011`) that names a different subject. Of the
  screenshots, only `evidence_04` was opened.
