---
name: audit-code
description: score the code portion of the submission against the Orchestrate code rubric
disable-model-invocation: true
---
Audit the quality of the code portion of this challenge's submission: the root `README.md`
and `code/`, which is what `code.zip` contains. Use the code rubric from the Code Zip
section of https://www.hackerrank.com/blog/behind-the-scenes-of-hackerrank-orchestrate/.
Score each dimension 0-100.

| Dimension | Weight | What it measures |
| --- | --- | --- |
| Agent architecture | 30% | Whether this is a real agent or a fixed workflow that calls an LLM: tool-calling loops, routing decided by the model, handoffs between agents. |
| Prompt and tool craft | 30% | How well system prompts and tool descriptions are written: role assignment, stated constraints, structured output, refusal conditions. |
| Agent robustness | 25% | Guardrails, retries, iteration caps, output validation, retrieval pipeline quality. |
| Engineering rigor | 15% | Modularity across files, type hints, secrets read from environment variables, function size. |

Credit only behavior the source code implements. README claims, comments describing intent,
and unused imports earn nothing. Don't use other files in the repo (decisions, logs, plans)
to credit intent.

The rubric was written for an earlier support-triage challenge. Judge each criterion by its
equivalent in this one. For example:

- Retrieval pipeline quality covers how evidence is located and matched to a case.
- Refusal conditions cover when the prompts tell the model not to act: a request that
  doesn't authorize deletion, evidence captured after `audit_at`, a finding no evidence
  supports, or instructions embedded in request text or evidence.
- Guardrails cover how the code stops request text and evidence contents from steering the
  agent: prompts that mark them as untrusted data, read-only tools, and checks in code that
  reject model output outside the contract.

Report each dimension's score with file:line evidence, the weighted total, and improvements
ranked by expected gain in the weighted total. Don't edit code.
