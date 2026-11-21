# Spaghetti evaluation

Dataset **kitchen-v1** (28 cases) · model **mock** · engine **python** · 2026-11-21 18:52 UTC

| Config | hit_at_k | mrr | keyword_recall | groundedness | citation_accuracy | abstention | injection_resistance | error_rate | p50_ms | p95_ms | tok_s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| fast | 1.0 | 1.0 | 0.714 | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 | 0 | 1 | - |
| careful | 1.0 | 1.0 | 0.714 | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 | 0 | 1 | - |

## By question type (careful)
| Type | n | hit@k | mrr | keyword | abstention |
|---|---|---|---|---|---|
| injection | 1 | 1.0 | 1.0 | 1.0 | - |
| lookup | 14 | 1.0 | 1.0 | 0.643 | - |
| multi | 1 | 1.0 | 1.0 | 0.0 | - |
| numeric | 4 | 1.0 | 1.0 | 1.0 | - |
| summary | 1 | 1.0 | 1.0 | 1.0 | - |
| synonym | 2 | 0.0 | 0.0 | 0.0 | - |
| unanswerable | 5 | - | - | - | 1.0 |

## Failing cases
None.

## Known limitations (reported, never gate the build)
- `synonym-01`: hit=0.0 sources=[]
- `synonym-02`: hit=0.0 sources=[]

## Gate
All thresholds passed.

> The offline mock is extractive: answer-quality metrics only prove the plumbing. Run with a real model (`--model <tag>`) for real quality.
