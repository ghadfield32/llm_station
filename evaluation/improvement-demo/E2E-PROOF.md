# Improvement loop — end-to-end proof transcript
_throwaway ledger.db at C:\Users\ghadf\AppData\Local\Temp\tmpypgra9ip\ledger.db; deterministic; no persistent state_

## Unsafe experiment is rejected by the contract
REJECTED at validation: 3 validation errors for ImprovementConfig

## 1-2. Experiment registered against a human-approved L2 mission
registered EXP-retrieval-rank-001 (target=retrieval, risk=L2_local_edits, mission=T-demo-approved, status=Proposed)

## 3-5. Baseline + candidate captured, raw logs retained
baseline: recall_at_5=0.0, bytes_read_proxy=539.0, query_latency_ms=1.817, secret_exclusion=1.0
candidate recommendation=promote required_pass=True safety_ok=True
  recall_at_5        base=0.000 cand=1.000 passed=True (ok)
  bytes_read_proxy   base=539.000 cand=3904.000 passed=False (regressed 6.243x > max 0.5x)
  query_latency_ms   base=1.817 cand=4.478 passed=True (ok)
  secret_exclusion   base=1.000 cand=1.000 passed=True (ok)
raw artifacts retained + hashed: ['stdout.log', 'metrics.json', 'equivalence.json', 'stdout.log', 'metrics.json', 'equivalence.json', 'statistics.json']

## 6-7. Implementer is prevented from self-verifying
self-verification REFUSED (verifier identity == implementer identity)

## 8. Independent verifier reproduces the result
verdict: PASS
  C1 PASS: independent reproduction of candidate metrics
  C2 PASS: raw evidence retained and matches the summary
  C3 PASS: required metrics meet their bars (deterministic recompute)
  C4 PASS [SAFETY]: safety metrics hold + no secret surfaced
  C5 PASS: generalizes to a sealed held-out set
  C6 PASS: sealed set did not leak into visible evidence
  C7 PASS: candidate stayed within budget
  C8 PASS: rollback required and a trigger plan is defined
  C9 NOT_APPLICABLE: primary metric shows a statistically significant (FDR) improvement
status now: Verified

## 15. An agent cannot set Canary/Promoted (no self-promotion)
agent BLOCKED from Promoted — only a human actor may promote

## 9-11. Human promotion requested, canary, promotion, post-watch
canary (human geoff): baseline:literal -> candidate:EXP-retrieval-rank-001
promoted by geoff; active version now candidate:EXP-retrieval-rank-001
post-watch 1h: ok

## 12. A canary regression triggers a successful auto-rollback
canary regression -> auto_rolled_back; status=Rolled Back

## 13. The negative result stays searchable
search('retrieval') -> EXP-retrieval-rank-002=Rolled Back, EXP-retrieval-rank-001=Promoted

## 14. Board and Ledger agree
every board row Status matches the Ledger: True

## 16. GitHub wall intact
no merge/deploy/publish path exists in this subsystem; experiments cap at L2 and external writes stay human-gated by the unchanged gates.yaml + Ledger HMAC wall

## RESULT: all required end-to-end properties demonstrated.