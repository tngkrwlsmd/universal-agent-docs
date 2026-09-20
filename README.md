# universal-agent-docs

`universal-agent-docs`는 특정 언어, 프레임워크, 클라우드 또는 AI 개발 도구에 종속되지 않는 범용 개발 에이전트 정책 번들이다.

목표는 정책 파일을 많이 만드는 것이 아니라, 개발 에이전트가 **무엇을 신뢰하고, 어떤 정책을 적용하고, 어떤 위험을 확인하고, 무엇을 실제로 검증했는지** 일관되게 판단하도록 하는 것이다.

## 구성

```text
universal-agent-docs/
├── AGENTS.md
├── POLICIES.md
├── PROJECT.md
├── POLICY_CONTRACT.json
├── POLICY_CONTRACT.schema.json
├── ROUTING_ALIASES.json
├── ROUTING_ALIASES.schema.json
├── RUNTIME_ACTION.schema.json
├── APPROVAL_ASSERTION.schema.json
├── PROTECTED_OVERRIDE.schema.json
├── README.md
├── LICENSE
├── requirements.txt
├── requirements.lock
├── conformance/
│   ├── README.md
│   ├── golden.json
│   └── invalid.json
├── scripts/
│   ├── validate.py
│   ├── package.py
│   └── package_consumer.py
├── tests/
│   ├── __init__.py
│   ├── test_policy.py
│   ├── test_fuzz.py
│   └── test_conformance.py
└── .github/workflows/
    ├── ci.yml
    ├── release.yml
    └── verify-release.yml
```

각 파일은 하나의 분명한 책임만 가진다.

- [`AGENTS.md`](AGENTS.md): 모든 에이전트가 처음 읽는 작은 root router와 공통 불변조건
- [`POLICIES.md`](POLICIES.md): 상세 정책의 사람용 절차·근거·설명 Source of Truth. Execution, Implementation, Testing 등 각 `policy-*` 섹션이 human-facing primary owner다.
- [`PROJECT.md`](PROJECT.md): 실제 프로젝트의 구조, 명령, 근거, readiness를 기록하는 단일 프로젝트 지도
- [`POLICY_CONTRACT.json`](POLICY_CONTRACT.json): canonical operation, 위험 floor, 실행 gate, binding/replay 등 **machine-enforceable 규칙의 normative Source of Truth**
- [`ROUTING_ALIASES.json`](ROUTING_ALIASES.json): 자연어 task를 canonical operation으로 추론하기 위한 비권위 fallback 힌트. 정책 의미를 소유하지 않는다.
- [`ROUTING_ALIASES.schema.json`](ROUTING_ALIASES.schema.json): routing alias hint 구조
- [`POLICY_CONTRACT.schema.json`](POLICY_CONTRACT.schema.json): machine contract 구조
- [`RUNTIME_ACTION.schema.json`](RUNTIME_ACTION.schema.json): runtime/tool adapter가 실행 직전에 제출하는 구조화된 action assertion 형식
- [`APPROVAL_ASSERTION.schema.json`](APPROVAL_ASSERTION.schema.json): explicit approval을 exact action digest + single-use execution nonce에 결박하는 wire contract
- [`PROTECTED_OVERRIDE.schema.json`](PROTECTED_OVERRIDE.schema.json): protected override를 `PROHIBITED_WITHOUT_OVERRIDE` imminent action에 정확히 결박하는 독립 wire contract
- [`LICENSE`](LICENSE): 코드·문서·스키마·테스트를 포함한 저장소 전체에 적용되는 Apache License 2.0
- `requirements.txt`: validator의 직접 dependency intent
- `requirements.lock`: CI/release용 hash-locked transitive dependency closure
- `scripts/validate.py`: bundle, routing, runtime action, exposure derivation, approval binding, readiness, protected override, distribution artifact 검증과 `PROJECT.md` bootstrap candidate 생성
- `scripts/package.py`: canonical ZIP, detached core trust manifest, detached full release manifest, ZIP SHA-256을 일관되게 생성하고 다시 검증하는 release packager
- `tests/test_policy.py`, `tests/test_fuzz.py`: 핵심 invariant 회귀 테스트와 deterministic property/fuzz 테스트
- `conformance/`: runtime/tool adapter가 canonical operation과 exposure fact를 정확히 보고하는지 검증하는 golden/invalid vector kit
- `.github/workflows/ci.yml`: Linux/macOS/Windows에서 bundle validation과 전체 테스트를 실행하는 CI
- `.github/workflows/release.yml`: canonical artifact를 만들고 GitHub Artifact Attestation/Sigstore provenance를 생성하는 release workflow
- `.github/workflows/verify-release.yml`: release run artifact의 signer workflow/source revision attestation, detached checksum, trust/release manifest를 소비자 관점에서 다시 검증하는 workflow

프로젝트와 배포 산출물의 이름은 항상 **`universal-agent-docs`**로 유지한다. 날짜나 임의 suffix를 파일명에 붙이지 않는다. Git commit이 변경 이력을 담당하고, machine compatibility는 `schema_version`이 담당한다. 실행 승인 binding은 사람이 붙인 bundle version 대신 `POLICY_CONTRACT.json`의 canonical JSON SHA-256인 `policy_contract_digest`를 사용하므로 정확한 정책 의미를 계속 고정할 수 있다.

## 시작 방법

이 저장소 자체를 개발·검증할 때는 clone한 source tree에서 아래 validator/테스트를 직접 실행한다. **다른 개발 프로젝트에 도입할 때는 source bundle을 project root에 overlay하지 않는다.** 해당 경우에는 아래 `Consumer installation layout`의 `universal-agent-docs-consumer.zip`을 사용하고, 기존 root `AGENTS.md`가 있으면 자동 덮어쓰기 대신 사람이 instruction hierarchy를 검토해 통합한다.

1. source repository 자체를 검토하는 경우 현재 tree를 그대로 사용한다. 소비 프로젝트에 설치하는 경우 `.agent-policy/` 아래 vendored core와 root consumer router 구조를 사용한다.
2. [`PROJECT.md`](PROJECT.md)의 machine-readable project facts와 사람이 읽는 구조 설명을 실제 프로젝트 근거로 채운다. consumer layout에서는 vendored template이 `.agent-policy/PROJECT.md`에 있으므로 이를 프로젝트 사실의 출발점으로 사용하되, 실제 프로젝트의 canonical fact 문서 위치는 해당 프로젝트 convention에 맞게 유지한다. 처음 도입하는 저장소라면 bootstrap candidate를 만들 수 있다. 자동 탐색 결과는 모두 `Inferred`이며 `Confirmed`로 자동 승격되지 않고, 기본 출력도 기존 `PROJECT.md`를 덮어쓰지 않는다.

```bash
python scripts/validate.py --bootstrap-project .
# 필요하면 별도 위치 지정
python scripts/validate.py --bootstrap-project . --bootstrap-output ./PROJECT.candidate.md
```

후보를 실제 source/config와 대조한 뒤 필요한 항목만 `Confirmed` 또는 근거 있는 `N/A`로 옮긴다.

3. 기본 bundle 검증을 실행한다.

```bash
python scripts/validate.py
```

필요한 primary-owner 정책만 에이전트 context에 넣고 싶다면 전체 `POLICIES.md` 대신 selector를 사용한다. selector는 Source of Truth를 분할하지 않고 해당 anchor의 완전한 섹션만 출력한다.

```bash
python scripts/validate.py --policy implementation
python scripts/validate.py --policy data_safety --policy security
```

4. 개발 준비 상태를 확인한다.

```bash
python scripts/validate.py --readiness development
```

5. 배포 작업까지 수행할 프로젝트라면 deployment readiness도 확인한다.

```bash
python scripts/validate.py --readiness deployment
```

validator의 언어 기준선은 Python 3.10+다. `requirements.txt`는 사람이 검토하는 직접 dependency intent를 유지하고, CI/release는 `requirements.lock`의 전체 transitive closure를 `--require-hashes`로 설치한다. 이 저장소의 release qualification matrix는 현재 Python 3.10과 3.14를 Linux/macOS/Windows에서 직접 검증한다. 3.11~3.13을 지원 불가로 선언하는 것은 아니지만, 해당 minor가 이 저장소 CI에서 독립적으로 qualification되었다고 주장하지 않는다.

회귀 테스트는 다음처럼 실행한다.

```bash
python -m unittest -v
```

`tests`가 Python package이므로 기본 unittest discovery에서도 전체 suite를 찾는다.

## 라우팅 모델

정책은 자연어 alias가 직접 결정하지 않는다. 먼저 계획을 stable한 **canonical operation ID**로 정규화한 뒤 operation catalog가 정책을 결정한다. canonical operation은 `POLICY_CONTRACT.json`, 자연어 phrase/stem/pattern fallback은 별도 `ROUTING_ALIASES.json`이 담당한다. 따라서 언어별 힌트를 확장해도 canonical semantics와 정책 계약은 불필요하게 바뀌지 않는다. 충분한 문맥이 없는 단일 일반어는 고유 Git/release 작업으로 승격하지 않는다.

```text
raw task ── task hint ─┐
planned operations ────┼→ canonical operation IDs → policy mapping
affected resources ────┘                         ↘ resource policy mapping
```

대표 ID는 `code.modify`, `build.execute`, `lint.execute`, `typecheck.execute`, `format.execute`, `test.execute`, `filesystem.generated_delete`, `filesystem.tracked_delete`, `filesystem.delete`, `database.schema_change`, `database.destructive_change`, `git.destructive_change`, `iam.change`, `cloud.resource_change`, `cloud.resource_delete`, `external.message_send`, `deploy.execute` 등이다. 에이전트가 계획을 만들 수 있는 환경에서는 자연어 대신 canonical ID를 `planned_operations`에 넣는 것을 우선한다.

위험 기반 테스트 시나리오는 `test.scenario.toctou`, `test.scenario.replay_idempotency`, `test.scenario.transaction_rollback`, `test.scenario.concurrency`, `test.scenario.security`, `test.scenario.file`, `test.scenario.external_system`으로 직접 계획할 수 있다. 이 ID들은 단순 문서 예시가 아니라 operation catalog에 등록되어 관련 Testing 및 primary-owner 정책으로 실제 routing된다.

```bash
python scripts/validate.py \
  --route "로그인 버그 고쳐줘" \
  --operation "code.modify" \
  --operation "test.execute" \
  --resource "src/auth/login.py"

# 실제 실행 전 enforcement에서는 해석된 canonical plan이 반드시 필요
python scripts/validate.py --routing-mode enforcement \
  --route "운영 DB에서 고객 데이터 조회해줘" \
  --operation database.read
```

호환을 위해 `--operation "run tests"` 같은 자연어도 canonical ID로 추론한다. fallback corpus는 `ROUTING_ALIASES.json`에서 관리한다. 기본 `advisory` routing에서는 미분류 task, 미해석 planned operation, task에서 유추된 operation이 plan에 빠진 경우를 `WARN`으로 표면화한다. `enforcement`에서는 **미해석 planned operation과 canonical plan 부재를 `FAIL`**로 처리하지만, 자연어 task 미분류와 task↔plan mismatch는 `WARN`으로 남긴다. 자연어 coverage가 실행 가능성의 단일 병목이 되지 않게 하고, 실제 실행 안전성은 action boundary에서 trusted runtime actual operation과 plan을 대조해 fail-closed한다.

각 canonical operation은 `effect_floor`를 가진다. 이는 실제 Effect 판정의 **최소값**이며 runtime은 target·environment·blast radius에 따라 더 높은 Effect로 올릴 수 있지만 근거 없이 더 낮출 수 없다. Exposure는 adapter가 `X2`처럼 최종 등급을 결정하지 않는다. adapter는 `data_classification`, `credential_class`, `tenant_scope`, `public_visibility`, `estimated_blast_radius`, `estimated_financial_impact`의 **원시 사실**과 environment를 보고하고, policy engine이 각 차원의 floor 중 최댓값을 계산한다. 명시적 `unknown` 값은 낙관하지 않고 보수적 floor를 가진다. 선택적 `declared_exposure`는 계산값을 올릴 수만 있고 낮출 수 없다. 모든 `test.scenario.*` operation은 실제 시나리오 실행을 전제로 `requires_execution_policy=true`이며 Execution policy를 명시적으로 포함한다. production DB read나 observability inspection처럼 read-only operation도 Execution의 Exposure 평가를 함께 받는다.

canonical operation ID는 adapter와 runtime 사이의 안정 API다. operation마다 `lifecycle_status`를 가지며 rename은 기존 ID를 즉시 바꾸는 대신 **새 ID 추가 → 기존 ID deprecated → replacement 명시** 순서를 사용한다. operation 제거와 의미 변경은 `schema_version` 변경이 필요하고, 의미를 바꾸지 않는 alias corpus 수정은 Git commit으로 추적한다. runtime adapter는 알 수 없는 operation ID를 거부해야 한다.

### 실행 직전 action boundary

계획 라우팅과 실제 실행 승인 판단은 분리한다. 실행 직전에는 **LLM이 계획에 적은 operation**과 **runtime/tool adapter가 실제 호출에서 독립적으로 보고한 canonical operation**을 비교해야 한다. actual operation이 plan에 없으면 실행을 차단한다. 일반 `--actual-action` alias mismatch는 anomaly warning이고, `terraform destroy`, `git reset --hard`, recursive object delete처럼 오탐 가능성이 낮은 high-confidence signature 누락만 defense-in-depth로 fail-closed한다.

먼저 raw exposure facts를 준비한다.

```json
{
  "data_classification": "internal",
  "credential_class": "service_credential",
  "tenant_scope": "single_tenant",
  "public_visibility": "none",
  "estimated_blast_radius": "service",
  "estimated_financial_impact": "bounded"
}
```

```bash
python scripts/validate.py --action-boundary \
  --operation deploy.execute \
  --actual-operation deploy.execute \
  --actual-action "kubectl apply -f deploy/" \
  --target production/cluster-a \
  --environment production \
  --exposure-facts ./exposure-facts.json \
  --correlation-id action-20260920-001 \
  --execution-nonce action-20260920-001-nonce
```

위 예에서 `deploy.execute`의 정적 floor는 L3이지만 production state change 규칙 때문에 effective Effect는 L4가 된다. Exposure는 environment floor와 raw fact floor를 함께 계산한다. adapter가 선택적으로 `--exposure X3`를 선언하면 더 보수적으로 올릴 수 있지만, `--exposure X0`처럼 policy-derived floor보다 낮은 값은 무시된다. `unknown` environment와 각 fact의 `unknown` 값도 보수적으로 처리한다. validator는 `action_gate`, `decision`과 함께 security-relevant action 전체를 묶은 `action_digest`를 계산하지만, **사용자 승인이나 protected override의 authority를 스스로 확립하지 않는다.** actual operation은 planning text가 아니라 신뢰 가능한 runtime/tool adapter가 제공해야 한다. `command.execute`는 runtime actual operation으로 **금지**되어 있다. shell 같은 범용 실행 surface는 구체 canonical operation으로 분류해야 하며, 의미를 분류할 수 없으면 action boundary가 fail-closed한다.

한글 phrase는 token boundary로 비교하고, 조사·어미 prefix가 필요한 항목만 명시적 stem으로 선언하며, 제한된 regex pattern은 문장이 필요한 고위험 표현에만 사용한다. canonical planned operation이 항상 우선이다.

### Structured runtime adapter assertion

`RUNTIME_ACTION.schema.json` v3는 vendor-neutral한 최소 wire contract다. runtime은 adapter identity/surface와 함께 `correlation_id`, **single-use `execution_nonce`**, planned/actual operations, affected resources, targets, environment와 raw `exposure_facts`를 구조화해 제출한다. 필요하면 runtime-observed Effect, raise-only `declared_exposure`, adapter-specific `semantic_details`를 함께 보낼 수 있다.

```json
{
  "schema_version": 3,
  "adapter": {
    "id": "kubernetes-adapter",
    "surface": "kubectl",
    "assertion_source": "tool_adapter"
  },
  "action": {
    "correlation_id": "action-20260920-001",
    "execution_nonce": "action-20260920-001-nonce",
    "planned_operations": ["cloud.resource_change"],
    "actual_operations": ["cloud.resource_change"],
    "affected_resources": ["deployment/api"],
    "targets": ["production/cluster-a/namespace-app"],
    "environment": "production",
    "exposure_facts": {
      "data_classification": "internal",
      "credential_class": "service_credential",
      "tenant_scope": "single_tenant",
      "public_visibility": "none",
      "estimated_blast_radius": "service",
      "estimated_financial_impact": "bounded"
    },
    "actual_action": "kubectl scale deployment api --replicas=4"
  }
}
```

파일 형태의 assertion은 다음처럼 구조와 action boundary를 함께 검사할 수 있다. `adapter_trust=UNVERIFIED`는 의도적이다. schema-valid payload만으로 producer identity나 transport integrity를 증명할 수 없기 때문이다.

```bash
python scripts/validate.py --runtime-action ./runtime-action.json
```

### Explicit approval assertion

`REQUIRE_EXPLICIT_APPROVAL`은 단순 텍스트 동의로 해제하지 않는다. `APPROVAL_ASSERTION.schema.json` v2는 승인 주체·scope·canonical operations·구체적 targets·environment·`correlation_id`·**`execution_nonce`**·`single_use=true`·`action_digest`·발급/만료 시각·authorization reference를 구조화한다. `action_digest v3`는 policy/bundle identity, adapter identity, nonce, planned/actual operations, resources, targets, environment, exposure facts, optional runtime escalation, 실제 action text와 **`semantic_details`**까지 묶는다. 따라서 target뿐 아니라 adapter나 semantic parameter가 바뀌어도 binding이 실패한다.

```json
{
  "schema_version": 2,
  "approval": {
    "approval_id": "apr-123",
    "issuer": "change-approver@example.invalid",
    "decision": "APPROVE",
    "scope": "one imminent production action",
    "issued_at": "2026-09-20T00:00:00Z",
    "expires_at": "2026-09-20T00:30:00Z",
    "operations": ["cloud.resource_change"],
    "targets": ["production/cluster-a/namespace-app"],
    "environment": "production",
    "correlation_id": "action-20260920-001",
    "execution_nonce": "action-20260920-001-nonce",
    "single_use": true,
    "action_digest": "sha256:<validator가 출력한 64자리 digest>",
    "authorization_reference": "change-ticket-123"
  }
}
```

```bash
python scripts/validate.py \
  --runtime-action ./runtime-action.json \
  --approval-assertion ./approval.json \
  --approval-ledger ./approval-consumption.sqlite \
  --consume-approval
```

`--consume-approval`은 local reference ledger에서 approval ID와 execution nonce를 원자적으로 한 번만 소비한다. 같은 approval/nonce를 다시 소비하면 `REPLAY_DETECTED`로 실패한다. ledger를 지정하지 않은 단순 검증은 `replay_protection=UNVERIFIED`다. validator는 schema/시간/action binding/replay consumption을 검증해도 issuer identity/authority는 인증하지 않으므로 `authorization=NOT_ESTABLISHED`를 유지한다. higher-authority runtime이 issuer와 transport를 인증한 뒤에만 실제 승인으로 취급해야 한다.

## Source of Truth

Source of Truth는 표현 계층을 분리한다. **machine-enforceable 규칙**(canonical operation, Effect/Exposure floor, gate, exact binding, replay)은 [`POLICY_CONTRACT.json`](POLICY_CONTRACT.json)이 normative owner다. **사람용 절차·근거·설명**은 [`POLICIES.md`](POLICIES.md)의 primary-owner 섹션이 소유한다. 둘이 enforcement 의미에서 불일치하면 Markdown이나 JSON 중 하나를 임의 우선하지 않고 **발견된 충돌을 invalid로 취급해 함께 수정한다.** 다만 validator가 `POLICIES.md`의 모든 자연어 문장을 의미론적으로 해석하는 것은 아니다. 자동 fail-closed 범위는 schema/contract/implementation 상수, risk matrix, routing/action-boundary semantics와 명시적 회귀 테스트처럼 **기계적으로 선언된 parity invariant**다. prose 전용 설명은 review/test에서 충돌이 발견되면 동일하게 invalid로 취급한다.

### 정책 무결성과 외부 trust anchor

무결성은 두 층으로 분리한다.

- **Core trust manifest (`.trust.json`)**: `POLICIES.md`, contract/schema, runtime/approval/protected-override schemas, validator/packager처럼 정책 의미와 enforcement를 소유하는 trusted core만 고정한다. 소비 프로젝트가 수정하는 `PROJECT.md`는 제외한다.
- **Full release manifest (`.release.json`)**: 공식 배포물의 모든 canonical distribution file과 ZIP artifact 자체의 SHA-256을 고정한다. README/test가 바뀌거나 ZIP 재조립이 일어나도 검출한다.

두 manifest 모두 **무결성 자료이지 publisher authentication 그 자체는 아니다**. release signing, protected CI artifact, 조직 정책 저장소 등 번들과 독립된 신뢰 경로로 전달하거나 외부 서명을 검증해야 한다. 같은 ZIP과 같은 비신뢰 채널로 함께 전달한 manifest만으로는 출처를 증명할 수 없다.

```bash
# known-good core에서 detached core manifest 생성
python scripts/validate.py --emit-trust-manifest ../universal-agent-docs.trust.json

# 설치된 core 검증
python scripts/validate.py --trusted-manifest ../universal-agent-docs.trust.json

# 실제 배포 ZIP의 core + full release 검증
python scripts/validate.py \
  --distribution ./dist/universal-agent-docs.zip \
  --trusted-manifest ../universal-agent-docs.trust.json \
  --release-manifest ../universal-agent-docs.release.json
```

신뢰할 수 없는 validator 자체가 교체된 상황까지 막으려면 higher-authority runtime 또는 독립 release verifier가 manifest/hash/signature를 별도로 확인해야 한다.

프로젝트 사실은 [`PROJECT.md`](PROJECT.md)에 `Observed / Intended / Contract / Evidence`를 구분해 기록한다. 문서에 `Confirmed`라고 썼다는 이유만으로 validator가 검증한 것으로 간주하지 않는다.

## Readiness

readiness는 세 범위를 분리해 보고한다.

- **Documented**: 필수 프로젝트 정보와 evidence reference가 문서에 채워져 있는가
- **Source-evidence-verified**: validator가 현재 파일시스템/Git에서 선언과 source evidence의 연결을 확인했는가. command가 실제 성공했다는 뜻은 아니다
- **Execution-verified**: build/test/deploy command 자체를 실제 실행해 성공을 확인했는가. 이 validator는 안전상 command를 자동 실행하지 않으므로 기본값은 `NOT_RUN`이다.

검증 불가능한 항목은 `MANUAL`로 남기며 evidence-verified `PASS`로 승격하지 않는다. 경로 fact는 evidence가 같은 경로를 가리켜야 하고, command/value fact는 각각 `command-source:`/`value-source:`로 문서 값과 evidence literal의 연결을 확인해야 자동 검증된다. `command-source:`는 comment-only occurrence를 거부하고 `package.json`에서는 `scripts` 값만 인정하지만, 여전히 command execution을 증명하지는 않는다. `PROJECT.md` machine block은 nested type과 선택적 component별 facts까지 방어적으로 검사하므로 잘못된 object/array 형태는 예외로 중단되지 않고 구조화된 `FAIL`로 반환된다. `reviewed_at`은 ISO-8601 date 또는 timezone-aware datetime이어야 하며 90일보다 오래되면 freshness warning을 낸다. `review.reviewed_paths`를 지정하면 HEAD가 바뀌었더라도 해당 path들이 reviewed revision 이후 변경되지 않은 경우 revision 검증을 유지할 수 있다.

### Bootstrap candidate와 readiness

`--bootstrap-project`는 repository를 관찰해 `PROJECT.inferred.md` 후보를 만든다. `src`/`services`/`packages` 같은 source 후보, `package.json`/`Makefile`의 command literal, runtime version source, component path와 Git revision을 탐색하지만 모든 자동 발견 fact는 `Inferred`로 남긴다. 따라서 bootstrap 자체가 documented readiness를 PASS로 만들지 못한다. 기존 output이 있으면 기본적으로 덮어쓰지 않으며, 잘못 추론된 후보를 사용자가 evidence에 맞게 교정하는 흐름을 전제로 한다.

## Adapter conformance kit

범용 정책 엔진의 가장 중요한 신뢰 경계는 runtime/tool adapter가 실제 action을 정확한 canonical operation과 exposure fact로 보고하는지 여부다. `conformance/golden.json`은 반드시 통과해야 하는 대표 mapping을, `conformance/invalid.json`은 under-reporting/opaque mapping처럼 반드시 차단되어야 하는 사례를 정의한다.

```bash
python -m unittest tests.test_conformance -v
```

새 adapter를 붙일 때는 이 corpus를 그대로 실행하고, adapter 전용 사례가 필요하면 같은 wire shape의 vector를 추가한다. 특히 `terraform destroy`, `git reset --hard`, public package/artifact publish, privileged credential 사용처럼 Effect/Exposure가 크게 달라지는 action은 구조화된 semantics와 실제 operation ID가 함께 맞아야 한다.

기본 corpus는 일반 개발 루프의 `build.execute`/`lint.execute`/`typecheck.execute`/`format.execute`, multi-operation build 흐름, generated/tracked/general delete 구분도 포함한다. `filesystem.tracked_delete`는 단순 파일명으로 L2가 되지 않으며 runtime adapter가 `recoverability=git_tracked_clean`과 `recovery_revision`을 제출해야 한다.

## Consumer installation layout

이 저장소 자체의 source/release bundle과 다른 프로젝트에 설치하는 consumer policy bundle을 구분한다. **source bundle을 다른 프로젝트 root에 그대로 overlay하지 않는다.** source bundle에는 이 저장소의 README, LICENSE, Python requirements, tests, GitHub workflows가 포함되므로 소비 프로젝트의 동명 파일과 충돌할 수 있다.

소비 프로젝트에는 `scripts/package_consumer.py`가 만드는 `universal-agent-docs-consumer.zip`을 사용한다. 이 artifact는 top-level `universal-agent-docs-consumer/` 아래에 root `AGENTS.md`와 `.agent-policy/`를 둔다. canonical upstream bundle 전체는 `.agent-policy/` 아래에 vendor되므로 기존 `README.md`, `LICENSE`, `requirements.txt`, `tests/`, `.github/workflows/`와 이름이 충돌하지 않는다.

```text
universal-agent-docs-consumer/
├── AGENTS.md
└── .agent-policy/
    ├── AGENTS.md
    ├── POLICIES.md
    ├── PROJECT.md
    ├── POLICY_CONTRACT.json
    └── ...
```

consumer root `AGENTS.md`는 canonical router에서 생성되며 정책 링크를 `.agent-policy/`로 다시 결박한다. readiness를 실행할 때는 `python .agent-policy/scripts/validate.py --project-root . --readiness development`처럼 소비 repository root를 명시해 evidence path와 Git revision을 실제 프로젝트 기준으로 검증한다. root `AGENTS.md`가 이미 있는 프로젝트에서는 **덮어쓰지 말고** 기존 instruction과 consumer router를 검토해 통합한다. consumer 계약은 `overwrite_existing_root_agents=false`, `extraction_requires_collision_check=true`를 명시하므로 ZIP을 기존 프로젝트 위에 무검토 overlay하는 방식은 지원하지 않는다.

```bash
python scripts/package_consumer.py --output-dir ./dist
python scripts/package_consumer.py \
  --verify ./dist/universal-agent-docs-consumer.zip \
  --release-manifest ./dist/universal-agent-docs-consumer.release.json
```

consumer verifier는 root router가 canonical source에서 생성되었는지, `.agent-policy/` 내부 upstream bundle이 자체 검증을 통과하는지, detached consumer release manifest가 ZIP과 모든 consumer path의 SHA-256에 정확히 결박되는지 확인한다.

## Release packaging

배포 ZIP, detached manifests, ZIP checksum을 수작업으로 조립하지 않는다. 공식 packager는 먼저 bundle validation을 실행하고 canonical manifest에 있는 파일만 deterministic ZIP에 넣은 뒤, **core trust manifest와 full release manifest를 각각 생성**하고 새 ZIP에 대해 distribution + 두 manifest 검증을 다시 수행한다. manifest와 checksum은 **ZIP 바깥**에 생성된다.

```bash
python scripts/package.py --output-dir ./dist
```

source packager 출력은 항상 `universal-agent-docs.zip`, `universal-agent-docs.trust.json`, `universal-agent-docs.release.json`, `universal-agent-docs.sha256` 네 파일이다. consumer packager는 `universal-agent-docs-consumer.zip`, `universal-agent-docs-consumer.release.json`, `universal-agent-docs-consumer.sha256`을 별도로 만든다. 날짜나 버전 suffix를 파일명에 넣지 않는다. trust/release manifest에는 `POLICY_CONTRACT.json`의 SHA-256이 포함되어 정책 계약 bytes와 함께 검증된다. manifest를 실제 trust anchor로 사용할 때는 ZIP과 같은 비신뢰 채널에만 두지 말고 독립된 protected release/CI/organization channel 또는 검증 가능한 서명과 함께 보관한다.

GitHub 저장소에서는 `.github/workflows/release.yml`을 수동 실행하면 동일한 canonical artifact를 생성하고 `actions/attest@v4`로 GitHub Artifact Attestation을 만든다. 이는 OIDC 기반 Sigstore 서명으로 build provenance를 제공한다. 저장소/플랜에서 attestation을 사용할 수 없는 경우에도 deterministic ZIP, SHA-256, detached manifests는 그대로 생성된다.

`.github/workflows/verify-release.yml`은 release workflow run ID와 **별도 trusted channel에서 얻은 40-hex `expected_source_sha`**를 함께 입력받는다. verifier는 해당 run이 `.github/workflows/release.yml`의 성공한 `workflow_dispatch`이고 `main`에서 실행되었는지 확인한 뒤 run의 `head_sha`가 외부 expected SHA와 정확히 같은지 검증한다. 그 후 각 canonical artifact에 대해 `gh attestation verify`로 repository, signer workflow, `refs/heads/main`, source digest를 함께 고정하고 detached ZIP checksum과 trust/release manifest를 검증한다. run 자신이 제공한 SHA만으로 trust expectation을 만들지 않는다.

GitHub Actions의 외부 action reference는 mutable major tag 대신 검토한 **full commit SHA**로 pin한다. branch protection/ruleset과 required review/CI는 repository governance의 별도 trust control이며 workflow 파일만으로 대체할 수 없다. provenance를 강한 trust signal로 사용하려면 `main` 보호 정책도 함께 설정하는 것이 권장된다.

## Distribution validation

배포 패키지 검증은 현재 working tree 전체가 아니라 **실제 배포 대상 디렉터리 또는 ZIP**을 명시적으로 검사한다. 단순 금지 파일 검사에 그치지 않고 canonical manifest의 필수 파일 전체, 예상 밖 파일, archive path traversal/absolute path, duplicate entry, symlink, 대소문자/Unicode 정규화 이름 충돌, 금지 artifact, 파일 수·개별/전체 해제 크기·압축률 한도를 **추출 전에** 확인한 뒤 안전한 임시 디렉터리에서 bundle validation도 다시 수행한다.

```bash
python scripts/validate.py --distribution ./dist/universal-agent-docs.zip
# full release manifest까지 있을 때
python scripts/validate.py --distribution ./dist/universal-agent-docs.zip --release-manifest ./dist/universal-agent-docs.release.json
```

ZIP은 최상위 `universal-agent-docs/` root를 가져야 한다. `AGENTS.md` 하나만 든 부분 패키지나 `../outside.txt` 같은 entry는 PASS할 수 없다. 테스트 실행 후 로컬에 생긴 `__pycache__`가 실제 배포물에 포함되지 않았다면 distribution validation에는 영향을 주지 않는다.

## Protected override

`PROHIBITED_WITHOUT_OVERRIDE`는 일반 task-level 요청이나 정적 프로젝트 설정만으로 해제되지 않는다. protected override는 `PROTECTED_OVERRIDE.schema.json`을 따르는 독립 객체이며 canonical operations, concrete targets, environment, correlation ID, **execution nonce**, **action digest**, `single_use=true`, scope와 발급·만료/authorization reference를 포함한다.

validator는 schema와 시간뿐 아니라 override의 digest/correlation/nonce/operations/targets/environment를 현재 `PROHIBITED_WITHOUT_OVERRIDE` action boundary와 정확히 비교해 `binding=VALID|INVALID`를 반환한다. 그래도 `authority=UNVERIFIED`, `task_approval=UNVERIFIED`, `authorization=NOT_ESTABLISHED`이며, protected override는 별도의 task-level explicit approval을 대체하지 않는다. higher-authority runtime은 override nonce도 single-use로 소비해야 한다.
Reference validator는 `--override-ledger`와 `--consume-override`로 SQLite 기반 atomic replay 검증을 제공하며, 동일 override ID 또는 execution nonce의 재사용은 `REPLAY_DETECTED`로 거부한다. 이 local ledger는 issuer identity/authority를 인증하지 않는다.

```bash
python scripts/validate.py \
  --runtime-action ./runtime-action.json \
  --protected-override ./override.json \
  --override-ledger ./override-consumption.sqlite \
  --consume-override
```

## Runtime integration

core는 vendor-neutral하며 기본 배포물에 vendor별 adapter 구현을 넣지 않는다. 대신 adapter가 지켜야 할 최소 assertion 형식은 `RUNTIME_ACTION.schema.json`으로 고정한다. Runtime이 `AGENTS.md`를 native 지원하면 그대로 사용한다. 특정 surface가 고정된 다른 파일명을 요구할 때만 **소비 프로젝트 쪽에서** root `AGENTS.md`를 가리키는 최소 bridge를 만든다.

Runtime 지원 방식은 바뀔 수 있으므로 도입 시 해당 도구의 공식 문서를 확인한다. bridge에 core 정책을 복사하지 않는다.

## 설계 원칙

- root router는 작게 유지한다.
- 한 규칙의 의미는 한 primary owner만 가진다.
- `Observed / Intended / Contract / Evidence`를 섞지 않는다.
- 위험은 `Effect × Exposure` 두 축으로 평가한다.
- 프로젝트별 규칙은 공통 안전정책을 강화할 수 있지만 암묵적으로 약화할 수 없다.
- `PASS`, `VERIFIED`, `완료`는 실제 evidence보다 강하게 표현하지 않는다.
- dependency/deployment resource fallback은 Node/Python/Rust/Go뿐 아니라 Maven/Gradle/.NET/Swift/Dart/Bun/Deno와 GitLab/Azure/CircleCI/Jenkins/Buildkite/Pulumi/CloudFormation 계열의 대표 파일까지 포함하되, canonical operation을 주 경로로 유지한다.
- 정책 시스템 자체가 일반 프로젝트보다 복잡해지지 않도록 파일과 개념을 최소화한다.

## License

이 저장소의 코드, 문서, 스키마와 테스트는 [Apache License 2.0](LICENSE)에 따라 사용할 수 있다. 재배포 또는 파생 작업에서는 해당 라이선스의 조건을 따른다.
