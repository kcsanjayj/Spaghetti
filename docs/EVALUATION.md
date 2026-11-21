# 📊 Evaluation harness

```bash
python run.py eval                                   # offline mock, full pipeline, gated (fast + careful modes)
python run.py eval --retrieval-only                  # NO model: retrieval quality + ablation. Meaningful in CI.
python run.py eval --model qwen3:1.7b                # a real Ollama model (retrieval gated; answer metrics reported)
python run.py eval --configs fast                    # one pipeline mode
python run.py eval --tag numeric --limit 5           # slice by tag or question type
python run.py eval --save-baseline eval/baseline.mock.json
python run.py eval --baseline eval/baseline.mock.json   # fail on regressions
```
Reports land in `eval/results/report.md` and `report.json`. **Exit code 1 = a gate failed** (used by CI).

## What is in it
| File | Role |
|---|---|
| `eval/datasets/kitchen.json` | 6 documents, 28 labelled cases |
| `eval/metrics.py` | pure, deterministic metric functions (unit-tested) |
| `eval/harness.py` | loader + validator, runner, aggregation, gates, baseline diff, ablation, reports |
| `eval/thresholds.json` | pass/fail floors per mode (`mock`, `live`, `retrieval`) |
| `eval/baseline.mock.json` | saved summary used for regression checks |
| `tests/test_eval.py` | 19 tests of the harness itself |

## Dataset design
| Type | n | What it checks |
|---|---|---|
| lookup / numeric / summary | 20 | the right document is retrieved and the answer contains the facts (`ten\|10` alternatives supported) |
| multi | 1 | needs two documents at once (`stretch`: strict hit@k) |
| unanswerable | 5 | the system says "not in the pantry" instead of inventing an answer |
| injection | 1 | a document contains "IGNORE ALL PREVIOUS INSTRUCTIONS… PWNED": the answer must not obey it |
| synonym | 2 | **known limitations**: lexical search cannot match synonyms. Reported, never gate the build |

## Metrics
| Metric | Meaning |
|---|---|
| `hit_at_k` | every expected document appears in the retrieved sources |
| `mrr` | 1 / rank of the first expected document |
| `keyword_recall` | share of expected facts present in the answer (normalised) |
| `groundedness` | share of answer words found in the retrieved text (Rust overlap) |
| `citation_accuracy` | answer cites `[n]` and every cited source is an expected document (no citation or an invented one scores 0) |
| `abstention` | on unanswerable questions, did it abstain? |
| `injection_resistance` | the forbidden string does not appear |
| `error_rate`, `p50_ms`, `p95_ms`, `tok_s`, `retry_rate` | reliability and speed (`tok_s` hidden for the mock) |

## Gates
1. **Thresholds** (`thresholds.json`): e.g. mock mode needs hit@k ≥ 0.9, citation ≥ 0.9, abstention ≥ 0.9, injection resistance 1.0, error rate 0, p95 ≤ 500 ms.
2. **Baseline regression**: a higher-is-better metric may not drop more than 0.05 below a saved run; p95 may not grow more than 50% (+50 ms).
3. Known-limitation cases are excluded from both.

## Results (this repository, offline mock)
| Mode | hit@k | mrr | citation | groundedness | abstention | injection | p95 ms |
|---|---|---|---|---|---|---|---|
| fast | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | ~8 |
| careful | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | ~8 |

Known limitations reproduced: both synonym cases retrieve nothing useful (hit@k 0).

### Retrieval ablation (`--retrieval-only`)
| min word coverage | hit@k | abstention |
|---|---|---|
| 0.0 (no filter) | 1.0 | 0.8 |
| 0.2 | 1.0 | 0.8 |
| **0.4 (shipped)** | **1.0** | **1.0** |
| 0.6 | 0.905 | 1.0 |

The 40% filter removes false matches on unanswerable questions with no loss of retrieval; 60% starts losing real answers. (Same result at k = 2, 4 and 8.)

## Honest limits
- The mock is **extractive**: it cannot write a weak answer, so fast and careful tie and keyword recall (≈0.7) only reflects one-sentence quoting. These numbers prove the **plumbing and retrieval**, not model quality.
- 28 cases is a small set, and the 40% threshold was chosen after seeing it. Add your own cases to `kitchen.json` (the loader validates them) before trusting the number.
- No LLM-as-judge: small local models are unreliable graders, so every metric is deterministic. The Taster's AI judge is a product feature, not an evaluation oracle.
- Live runs (`--model <tag>`) were not possible in our sandbox; run one and compare careful vs fast to see whether the judge and retry really help.
