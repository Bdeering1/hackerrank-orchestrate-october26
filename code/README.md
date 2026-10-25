# Ghost Data deletion audit

Audits every request in `dataset/deletion_requests.csv` and writes `output.csv` at the
repository root. One LLM call per distinct request text decides whether the person asked for
deletion. The rest is deterministic Python.

## Setup

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/). Put this directory at the
repository root as `code/`, next to `dataset/`.

```bash
cd code
uv sync
```

Intent routing calls Claude Haiku 5.5 through Vercel AI Gateway. Add the key to `.env` at
the repository root:

```text
AI_GATEWAY_API_KEY=<your key>
```

## Run

```bash
uv run --env-file ../.env python main.py
```

This writes `../output.csv`. The LLM client caches responses in `.cache/llm/` at the
repository root, keyed by prompt, so a rerun on the same requests makes no model calls. `--usage <path>`
writes per-model call and token counts as JSON. `--dataset`, `--requests` and `--output`
override the default paths.

To check an output file against the submission contract:

```bash
uv run python -m evaluation.main validate
```

## How it works

1. **Intent** (`intent.py`). Haiku labels each request text, in any language, with a
   JSON-schema response at temperature 0. The prompt treats the text as untrusted data.
   Access, export, correction and opt-out requests get `NOT_APPLICABLE` and `[]`.
2. **Identity** (`identity.py`). The current snapshot plus `user_audit_log.csv` give every
   email, phone, email hash and `user_id` the person has held. Matching is exact after
   normalization and never uses names.
3. **Evidence** (`evidence.py`). Readers for SQL (loaded into SQLite), JSON, logs and text
   records turn each file into observations and coverages. An observation is one record's
   state in one file. A coverage is a snapshot that lists every record of a system copy, so
   a record missing from it is absent. Replica tables in topology snapshots count as
   separate copies.
4. **Linking** (`audit.py`). The audit includes a resource when an observation carrying one
   of the subject's identifiers, or a `LINK_RESOURCE_IDENTITY` activity row, ties it to them
   at or before `audit_at`. It drops links older than the subject's previous deletion audit.
   If no account links, a `deletion_worker` delete claim logged near `reported_at` can
   nominate one.
5. **State.** A copy's state is its latest proof at or before `audit_at`. Activity results and
   `reported_status` never count as proof.
6. **Policy.** `deletion_rules.csv` sets the target state per category. An unmet condition
   or expired retention falls back to delete. Data flows must end disabled and backups
   blocked.
7. **Plan.** A resource with any copy off target gets a finding, a remediation and a
   verification. A case is `COMPLETE` only when every resource is on target, and then it
   gets verifications that cite the proving evidence. Steps sort by operation, so flows are
   disabled and restores blocked before records change. Citations must be captured at or
   before `audit_at`.

Each data category is a module in `ghost_audit/categories/`. It declares the policy
category, the default system, the table, collection, record and log names that identify it,
and how to read a record's state. The package discovers modules on import, so adding a
category touches no shared code.

## Evaluation

```bash
uv run --env-file ../.env python -m evaluation.main
```

Scores the 32 public samples plus the custom cases in `evaluation/cases/`, prints token
usage, and saves the run under `eval_runs/` at the repository root. `--holdout` scores the
holdout suite instead. `--full-set` also runs all 518 requests and diffs them against the
baseline run. `promote <run_id>` makes a run the baseline.

Results and custom cases are in `evaluation/evaluation_report.md`. Token usage for the
submitted run is in `evaluation/usage_report.md`.

## Development

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run basedpyright
uv run lint-imports
```

Tests run the real entry point against a small fixture dataset with a fake LLM transport.
pytest-socket blocks network access.

## Known gaps

- The agent does not read PDFs or screenshots, so it misses facts that appear only there.
- Cache entries and email-delivery logs produce no steps. Their activity rows carry no
  subject identifier.
- A deletion request with no linked resource gets `NOT_APPLICABLE`, because the validator
  rejects `COMPLETE` rows with no steps.
