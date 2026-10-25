# Evaluation report

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

The holdout suite (`cases/holdout.txt`) is samples case_04, case_12 and case_30 plus case_902
and case_905. Holdout cases are left out of default runs and promotion and are never used as
prompt examples. `uv run python -m evaluation.main --holdout` scores them and compares the
result with the previous holdout run.
