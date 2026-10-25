# Usage report

Token usage for the full-dataset run that produced the submitted `output.csv`: 518 requests
from `dataset/deletion_requests.csv`, run on commit `1c1ab68` on 2026-10-25 with an empty LLM
cache, so every model call was made and counted.

```bash
uv run --env-file ../.env python main.py --usage usage.json
```

## Models

| Provider | Model | Access | Used for |
| --- | --- | --- | --- |
| Anthropic | `claude-haiku-5.5` | Vercel AI Gateway | Intent routing and PDF/screenshot extraction |

No other model is called. Identity, linking, state, policy and planning are deterministic.

## Calls and tokens

| Provider | Model | Calls | Input tokens | Output tokens | Total tokens | Avg tokens/request | Est. cost | Est. cost/request |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Anthropic | claude-haiku-5.5 | 420 | 286,432 | 46,212 | 332,644 | 642.17 | $0.0517 | $0.000100 |
| **Overall** | all models | **420** | **286,432** | **46,212** | **332,644** | **642.17** | **$0.0517** | **$0.000100** |

Averages divide by the 518 requests.

- 398 intent calls, one per distinct request text. The run classifies the 375 distinct
  texts in `deletion_requests.csv` plus the sample request texts, because a subject's
  earlier request can come from either file.
- 22 extraction turns across the 15 PDFs and screenshots. A file takes one turn per
  `read_page` call plus a final `submit`.
- No call was retried.

## Cost basis

Cost uses Anthropic list prices for Claude Haiku 5.5 at prompts under 100K tokens: $0.10 per
million input tokens and $0.50 per million output tokens. Gateway charges may differ. Prices
live in `evaluation/usage.py`.

A rerun with the cache in `.cache/llm/` makes no model calls and costs nothing.
