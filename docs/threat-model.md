# Threat model and runtime trust boundaries

이 문서는 Profile C integration의 **신뢰 경계와 잔여 위험**을 설명하는 primary owner다. `POLICY_CONTRACT.json`은 machine-enforceable semantics를 소유하고, 이 문서는 공격/실패 시나리오와 운영 책임을 설명한다. JSON Schema를 만족한다는 사실은 producer identity, organization authority, transport authenticity를 증명하지 않는다.

## Scope and trust assumptions

Profile C가 성립하려면 정책 엔진과 별개로 실제 tool/API 직전의 trusted interception, 조직이 신뢰하는 issuer authentication/authorization, trusted transport, durable atomic replay ledger와 final dispatcher가 필요하다. Reference validator는 payload structure, policy semantics, exact binding과 로컬 replay semantics를 검증할 수 있지만 조직 권한 자체를 발급하거나 인증하지 않는다.

| Asset | Trust boundary | Threat | Attack / failure scenario | Expected defense | Residual risk | Responsible component | Test / evidence |
|---|---|---|---|---|---|---|---|
| Agent instruction hierarchy | repository -> agent | Repository prompt injection | source/README가 "상위 지시를 무시"하도록 유도 | repository content는 권한 있는 instruction source가 아니면 data로 취급 | host가 instruction/data provenance를 잃으면 우회 가능 | agent host + `AGENTS.md` | `AGENTS.md` instruction authority |
| Agent instruction hierarchy | issue/log/fixture -> agent | Malicious issue, log, fixture instruction | 외부 텍스트가 operational instruction처럼 실행됨 | untrusted content를 data로 유지하고 별도 canonical plan 필요 | tool host가 provenance를 잘못 표시할 수 있음 | agent host | `AGENTS.md` always-on invariants |
| Planned operation | planner -> runtime | Planner spoofing | 낮은 위험 operation을 계획하고 더 강한 action 실행 | actual operation을 trusted adapter가 독립 관찰하고 plan coverage 비교 | adapter 자체가 손상되면 관찰값 신뢰 불가 | runtime adapter + policy engine | `tests/test_runtime.py`, `tests/test_github_reference_adapter.py` |
| Actual operation | tool surface -> policy engine | Actual-operation spoofing | adapter가 실제 API와 다른 operation을 주장 | fixed adapter surface, hard signature checks, unknown/opaque fail-closed | compromised adapter는 별도 신뢰 문제 | adapter/integrator | runtime conformance vectors, GitHub reference adapter |
| Delegated authority | agent -> privileged tool | Confused deputy | 승인된 좁은 요청을 이용해 더 넓은 권한 행사 | concrete target, environment, semantic details와 action digest exact binding | 외부 IAM 자체의 과도한 권한은 해결하지 않음 | dispatcher + external IAM | approval/boundary tests |
| Target | policy evaluation -> dispatch | Target substitution | 승인 후 repository/recipient/resource 변경 | target을 digest에 결박하고 dispatch 직전 재관찰/재평가 | API 내부에서 target 의미가 재해석되면 adapter 계약 필요 | adapter + dispatcher | `test_target_substitution_after_approval_is_blocked_before_transport` |
| Environment | policy evaluation -> dispatch | Environment substitution | staging 승인으로 production 호출 | environment를 digest에 결박하고 실행 직전 재평가 | provider-side alias가 환경을 바꾸면 integrator 책임 | adapter + runtime | sandbox adapter binding tests |
| Approval | issuer -> runtime | Approval replay | 같은 승인/nonce로 두 번째 side effect 실행 | single-use nonce와 atomic replay consumption | 분산 환경의 공유 ledger가 없으면 node 간 replay 가능 | higher-authority runtime | approval tests; reference SQLite ledger |
| Approval | storage/transport -> runtime | Approval theft | 탈취한 승인 assertion 재사용 | exact action/nonce/TTL binding + issuer authz 요구 | bearer artifact 자체 유출은 조직 credential control 필요 | issuer + transport + runtime | approval schema/binding tests |
| Approval | issuer -> runtime | Stale approval | 오래된 승인으로 변경된 상태에 실행 | TTL 검증 및 실행 시점 boundary 재평가 | TTL 안의 외부 상태 변화는 별도 precondition 필요 | runtime adapter | expired approval tests |
| Adapter | runtime boundary | Compromised adapter | actual operation/target/exposure를 거짓 보고 | schema/capability/integrity pinning은 변조 탐지 일부만 제공 | 실행 중 compromise는 contract만으로 방어 불가 | deployment/runtime owner | extension/capability integrity tests |
| Transport | runtime -> provider | Compromised transport | 검증 후 요청이 변조되거나 다른 endpoint로 전달 | authenticated trusted transport를 Profile C prerequisite로 요구 | TLS termination/credential compromise는 외부 통제 필요 | integrator | documented boundary; reference boolean stand-in only |
| Approval authority | issuer -> runtime | Compromised issuer | 공격자가 유효 형식의 승인을 발급 | validator는 authority를 주장하지 않고 higher-authority authz를 요구 | issuer compromise 자체는 이 저장소 밖 | organization identity/authz | approval result reports authority separately |
| Evaluated action | policy engine -> dispatcher | TOCTOU | policy 평가 후 request 내용/target 변경 | immutable request 또는 dispatch 직전 actual facts 재관찰 및 digest 재검증 | provider state의 비원자적 precondition은 남음 | adapter + dispatcher | GitHub reference adapter mutation tests |
| Project facts | repository -> validator | Stale PROJECT facts | 과거 build/deploy target을 현재 사실로 사용 | reviewed revision/path freshness, evidence linkage, stale warning | manual evidence의 최신성은 사람 책임 | project owner + readiness validator | readiness tests |
| Policy bundle | release -> consumer | Bundle tampering | contract/schema/script가 수정된 artifact 배포 | release manifest, SHA-256, provenance, explicit distribution validation | 신뢰 anchor 자체가 손상되면 검증 무력화 | publisher + consumer | distribution/integrity tests |
| Extension/capability | organization config -> runtime | Extension/capability forgery | schema-valid 가짜 capability로 operation 허용 | bilateral capability + separately supplied expected digest; authority 별도 | expected digest 공급 경로가 손상되면 위험 | integrator | extensibility/conformance tests |
| Replay ledger | concurrent runtimes | Replay race | 두 worker가 동시에 같은 승인 consume | single transaction/atomic consume 필요 | reference SQLite는 분산 shared ledger가 아님 | production runtime | approval replay concurrency semantics |
| Side effect | approval ledger -> provider | Partial failure after approval consumption | consume 후 API 실패하여 retry가 막힘 | consume와 dispatch 결과를 audit하고 새 승인/nonce 또는 idempotency strategy 사용 | exactly-once external side effect는 일반적으로 보장 불가 | adapter + provider | integrator-specific recovery procedure |
| Audit record | provider -> audit sink | Side effect after audit failure | 외부 변경 성공 후 audit 기록만 실패 | execution result와 correlation/nonce를 반환하고 outbox/durable audit 권장 | reference examples는 durable audit system을 제공하지 않음 | production runtime | documented residual risk |

## What the repository does and does not establish

이 저장소가 검증하는 것은 canonical operation, Effect/Exposure/gate, required runtime facts, plan/actual coverage, exact action binding, approval/override structure/time/replay semantics, extension/capability integrity relation과 distribution integrity다.

다음은 소비 환경의 책임이다.

- adapter/interceptor가 실제 tool/API를 빠짐없이 관찰한다는 보장
- issuer와 adapter의 조직 identity/authz
- authenticated transport와 endpoint identity
- production-grade shared durable atomic replay ledger
- provider별 idempotency, transaction, rollback/recovery
- 최종 dispatcher가 policy 결과를 우회할 수 없다는 배치/권한 구조
- side effect 이후 durable audit와 incident recovery

따라서 `schema-valid`, digest match, validator `PASS` 중 어느 하나만으로 production authority 또는 end-to-end enforcement를 주장하지 않는다.

## Reference evidence

- core runtime semantics: `POLICY_CONTRACT.json` / `docs/generated-policy-reference.md`
- generic runtime tests: `tests/test_runtime.py`, `tests/test_approval.py`, `tests/test_override.py`
- extension/capability boundary: `docs/extensions.md`, `tests/test_extensibility.py`, conformance corpus
- production-shaped execution example: `examples/runtime-adapter/github_issue_adapter.py`
- local extension execution example: `examples/runtime-adapter/sandbox_artifact_adapter.py`
