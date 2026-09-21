# Adoption profiles and quick start

`universal-agent-docs`는 하나의 "보안 모드"가 아니라, 같은 policy bundle을 어디까지 실제 runtime에 연결했는지에 따라 보장이 달라지는 도입 경로를 제공한다. 이 문서의 profile 이름은 **도입 설명을 위한 문서 분류**이며 `POLICY_CONTRACT.json`의 machine-enforceable state가 아니다.

## 구현 중립성의 범위

policy model, canonical operation ID, `POLICY_CONTRACT.json`과 language-neutral conformance corpus는 특정 구현 언어를 전제로 하지 않는다. 다른 언어의 policy engine은 repository의 Python module을 import하지 않고 JSON contract/corpus를 구현해 동일 normative result를 낼 수 있다.

현재 저장소가 제공하는 **reference implementation과 packaging tooling은 Python 3.10+ 기반**이다. 또한 공식 release/provenance의 reference workflow는 GitHub Actions, GitHub Release와 attestation을 사용한다. 다른 CI/CD 또는 artifact repository도 같은 trust property를 구현할 수 있지만, 해당 플랫폼용 adapter/workflow가 이 저장소에 포함되거나 qualification되었다는 뜻은 아니다.

## Profiles at a glance

| Profile | 목적 | 제공하는 보장 | 제공하지 않는 보장 |
|---|---|---|---|
| **A — Guidance** | 개발 에이전트에게 일관된 지침과 프로젝트 사실 제공 | agent instruction hierarchy, human-readable policy, project fact discipline | tool interception, actual-operation verification, approval enforcement, replay protection |
| **B — Validated** | policy bundle과 계획/위험 판정을 자동 검증 | bundle/schema validation, readiness, canonical routing, Effect/Exposure/gate calculation, distribution integrity | trusted actual-operation assertion이 없으면 실행 차단 보장 없음; schema-valid runtime payload만으로 producer authenticity 보장 없음 |
| **C — Enforced Runtime** | 실제 action/tool boundary에서 fail-closed enforcement | B의 contract/reference validation + 소비 환경에 연결된 trusted interception, exact binding, replay consumption, 실제 allow/block 집행 | bundle만으로 완성된 범용 runtime이 제공되는 것은 아님; interception·identity/transport·shared ledger·executor는 integration 책임 |

Profile은 누적적이다. C는 B와 A의 기반을 포함한다.

Profile은 **설치 artifact의 파일 subset을 뜻하지 않는다.** 공식 consumer ZIP은 A/B/C 모두 같은 full `.agent-policy/` bundle을 제공한다. 차이는 설치 파일을 삭제하는 데 있지 않고, A는 guidance만 사용하고 B는 validator/CI를 활성화하며 C는 runtime boundary까지 실제로 연결하는 데 있다.

## Which profile should I use?

다음 중 가장 먼저 "예"가 되는 질문을 선택한다.

1. **에이전트가 저장소 규칙과 프로젝트 사실을 일관되게 읽게 하는 것만 필요한가?** → A
2. **CI에서 bundle/readiness/routing/risk/integrity를 자동 검증하고 싶은가?** → B
3. **실제 shell/tool/API 호출 직전에 allow/block/approval/override를 강제해야 하는가?** → C

production, customer data, privileged credentials, external/public side effects를 자동 실행하는 환경에서는 C가 목표 상태다. A/B만 사용하는 동안에는 해당 runtime이 스스로 실행을 차단한다고 주장하지 않는다.

## Minimal consumer installation

### Artifact acquisition

먼저 [GitHub Releases](https://github.com/tngkrwlsmd/universal-agent-docs/releases)를 확인한다.

가능하면 [GitHub Releases](https://github.com/tngkrwlsmd/universal-agent-docs/releases)의 최신 immutable SemVer Release에서 consumer ZIP을 사용한다. published Release가 아직 없거나 source checkout 자체를 검증하려는 경우에만 upstream source에서 consumer ZIP을 직접 build한다.

```bash
git clone https://github.com/tngkrwlsmd/universal-agent-docs.git
cd universal-agent-docs
python -m pip install --require-hashes --requirement requirements.lock
python scripts/package_consumer.py --output-dir dist
python -m zipfile -e dist/universal-agent-docs-consumer.zip /tmp/uad-consumer
```

이 source-built artifact는 package self-validation과 local adoption에는 사용할 수 있지만, published immutable release의 publisher authenticity/provenance를 대신하지 않는다. production에서 official SemVer Release를 사용할 수 있다면 Release의 consumer ZIP을 우선하고, trusted `release_tag`와 별도 채널에서 확보한 `expected_source_sha`로 `.github/workflows/verify-release.yml`을 실행해 release/build provenance를 확인한다.

### Staging and install

공식 source bundle을 소비 프로젝트 root에 그대로 overlay하지 않는다. consumer ZIP을 staging 위치에 푼 뒤 `.agent-policy/`와 generated root `AGENTS.md`를 검토하여 적용한다.

```text
/tmp/uad-consumer/
└── universal-agent-docs-consumer/
    ├── AGENTS.md
    └── .agent-policy/
        ├── AGENTS.md
        ├── POLICIES.md
        ├── PROJECT.md
        ├── POLICY_CONTRACT.json
        ├── scripts/
        ├── conformance/
        └── ...
```

소비 프로젝트에 적용할 때:

1. `.agent-policy/`가 이미 있으면 덮어쓰지 말고 기존 설치와 version/provenance를 먼저 확인한다.
2. root `AGENTS.md`가 없으면 generated router를 복사할 수 있다.
3. root `AGENTS.md`가 이미 있으면 **자동 overwrite하거나 단순 append하지 않는다**. 기존 project-specific instructions를 보존하고 두 instruction hierarchy를 사람이 검토해 병합한다.
4. vendored `.agent-policy/PROJECT.md`는 template이므로 그대로 두고 readiness PASS를 기대하지 않는다.

기존 root `AGENTS.md` 병합의 최소 예:

```markdown
# Project instructions

- Use pnpm.
- Never edit generated migrations manually.

## Universal agent policy

Before making repository changes, read and apply `.agent-policy/AGENTS.md` in addition to the project-specific rules above.
If the two instruction sets appear to conflict, do not silently discard either one; resolve the instruction hierarchy explicitly.
```

이 예시는 universal policy router를 연결하는 최소 형태일 뿐이다. agent/runtime마다 instruction discovery 규칙이 다를 수 있으므로 `.agent-policy/AGENTS.md`가 자동으로 적용된다고 가정하지 않는다. 충돌이 있으면 사람이 hierarchy를 검토해야 하며, 이 merge 단계는 현재 자동화되지 않는다.

consumer contract는 `overwrite_existing_root_agents=false`와 `extraction_requires_collision_check=true`를 명시한다. 일반 unzip/copy 도구가 이 규칙을 대신 강제한다고 가정하지 않는다.
## PROJECT bootstrap → review → readiness

기본 consumer installation의 **canonical project facts 문서는 `.agent-policy/PROJECT.md`**다. 설치 직후 이 파일은 template이며, bootstrap candidate와는 역할이 다르다.

소비 프로젝트 root에서 candidate를 생성한다.

```bash
python .agent-policy/scripts/validate.py \
  --bootstrap-project . \
  --bootstrap-output ./PROJECT.candidate.md
```

`PROJECT.candidate.md`는 repository를 관찰해 만든 **임시 review artifact**다. bootstrap은 source root, command source, runtime source, component 후보를 수집하지만 모든 자동 발견 fact를 `Inferred`로 유지하고 `Confirmed`로 자동 승격하지 않는다.

다음 순서를 따른다.

1. `PROJECT.candidate.md`를 실제 source/config와 대조한다.
2. 맞는 fact만 사람이 `Confirmed`로 판단하거나 근거 있는 `N/A`로 정리한다.
3. 검증 가능한 `path:`, `command-source:`, `value-source:` evidence를 연결한다.
4. 검토 결과를 기본 canonical facts 문서인 `.agent-policy/PROJECT.md`에 반영한다. candidate 자체를 canonical 문서라고 간주하지 않는다.
5. development readiness를 실행한다.

```bash
python .agent-policy/scripts/validate.py \
  --project-root . \
  --readiness development
```

프로젝트 convention 때문에 다른 facts 문서를 canonical로 사용해야 한다면 validator의 `--project-file`을 명시할 수 있다.

```bash
python .agent-policy/scripts/validate.py \
  --project-root . \
  --project-file ./docs/PROJECT.md \
  --readiness development
```

custom path를 선택하면 validator만 바꾸고 끝내지 말고, root/project agent instructions도 같은 canonical facts 위치를 가리키도록 함께 수정한다.

deploy까지 자동화한다면 같은 canonical facts 문서로 deployment readiness도 확인한다.

```bash
python .agent-policy/scripts/validate.py \
  --project-root . \
  --readiness deployment
```

`documented=PASS`, `evidence_verified=PASS`여도 build/test/deploy command가 실제 성공했다는 뜻은 아니다. validator는 기본적으로 command를 실행하지 않으므로 `execution_verified=NOT_RUN`이다.
## Profile A — Guidance

### Required pieces

- project root `AGENTS.md` 또는 기존 root instructions에 병합된 consumer router
- `.agent-policy/AGENTS.md`
- `.agent-policy/POLICIES.md`
- project facts (`.agent-policy/PROJECT.md` 또는 프로젝트가 정한 canonical facts 문서)

### Typical use

- coding agent에게 공통 invariant와 policy routing을 읽히기
- 변경 전에 PROJECT facts와 human policy를 참고시키기
- 조직의 리뷰/승인 절차를 사람이 수행하기

### Security boundary

Guidance는 **문서와 instruction을 제공할 뿐 실행을 intercept하지 않는다**. 모델이 지침을 읽었다는 사실은 shell/API/tool 호출이 기술적으로 차단된다는 뜻이 아니다. approval text를 적었다고 atomic single-use approval enforcement가 생기는 것도 아니다.

### Upgrade to B

validator와 hash-locked dependency를 실행하고 CI에 bundle/readiness 검증을 추가한다.

## Profile B — Validated

### Required pieces

A에 더해:

- `POLICY_CONTRACT.json` 및 schema/wire contracts
- `scripts/validate.py` + `scripts/validation/`
- `requirements.lock`
- CI validation
- distribution/trust/release manifest verification이 필요한 경우 공식 package/verifier

### Typical commands

```bash
python -m pip install --require-hashes --requirement .agent-policy/requirements.lock
python .agent-policy/scripts/validate.py
python .agent-policy/scripts/validate.py --project-root . --readiness development

python .agent-policy/scripts/validate.py \
  --routing-mode enforcement \
  --route "run tests" \
  --operation test.execute
```

`--routing-mode enforcement`의 **enforcement는 routing validation 범위**다. unknown/unresolved planned operation을 계획 단계에서 fail-closed하지만 tool/API/shell 호출을 직접 intercept하거나 차단하지 않는다. Profile C의 runtime enforcement와 동일하지 않다.

B에서는 canonical plan, Effect/Exposure, gate를 계산하고 malformed/unknown policy input을 fail-closed할 수 있다. 그러나 **trusted runtime/tool adapter가 실제 호출을 독립적으로 보고하지 않는다면 계산된 gate가 실제 side effect를 막는다는 보장은 없다**.

`RUNTIME_ACTION.schema.json`을 만족하는 JSON을 받았다는 사실만으로 adapter producer identity나 transport integrity가 확립되는 것도 아니다.

### Upgrade to C

실제 tool/action boundary에 adapter를 연결하고 trusted assertion source, exact action binding, single-use ledger, higher-authority issuer authentication을 구성한다.

## Profile C — Enforced Runtime

Profile C는 별도 ZIP이나 완성된 범용 runtime 제품이 아니라, 이 저장소의 policy/runtime contract를 **실제 side-effect boundary에 신뢰 가능하게 연결한 통합 상태**다. bundle을 설치하고 validator를 실행하는 것만으로 C가 되지 않는다.

### Required pieces

B에 더해 최소 다음이 필요하다.

- 실제 tool/API/action을 실행 전에 intercept하는 runtime adapter 또는 equivalent trusted boundary
- planner와 독립적으로 관찰·분류한 `actual_operations`
- affected resources, concrete targets, environment, raw exposure facts
- unique correlation ID와 imminent action별 single-use execution nonce
- 현재 runtime assertion으로 계산한 action digest
- higher-authority identity/authorization으로 인증된 explicit approval / protected override issuer
- approval/override를 실행 직전에 원자적으로 소비하는 shared replay ledger
- adapter assertion producer와 transport integrity에 대한 신뢰 경계
- 최종 gate 결과를 실제 tool 실행에 반영하는 executor/dispatcher
- 지원하지 않거나 충분히 분류할 수 없는 action의 fail-closed 처리
- production 사용 시 trusted release/provenance verification

### Bundle과 integrator의 책임 분리

| 책임 | 이 저장소의 contract/reference implementation | 소비 환경 / higher-authority runtime |
|---|---|---|
| planned operation | canonical operation catalog와 routing/validation semantics 제공 | planner가 task를 canonical plan으로 구성 |
| actual operation | actual-vs-planned 검증 규칙과 wire schema 제공 | interceptor가 imminent action을 독립적으로 관찰·분류 |
| Effect / Exposure / gate | raw facts에서 Effect/Exposure/gate를 계산·검증 | target/environment/raw facts를 신뢰 가능한 source에서 수집 |
| action digest | deterministic digest format과 reference 계산 제공 | 실행 직전 assertion을 고정하고 digest가 바뀌면 approval을 새로 획득 |
| approval / override | exact binding, TTL, schema와 validation semantics 제공 | issuer identity/authority를 인증하고 assertion을 발급 |
| replay | single-use/replay semantics와 conformance 제공 | 여러 worker에서 공유되는 atomic consumption ledger 운영 |
| enforcement | allow/block 판단을 계산하는 reference validator 제공 | gate가 충족되기 전 실제 tool/API/action 호출을 물리적으로 막음 |
| producer/transport trust | schema로 필요한 payload shape를 정의 | adapter producer 인증, transport integrity/freshness 보장 |
| provenance | GitHub 기반 reference verification workflow 제공 | 배포 채널에 맞는 trusted expectation과 provenance trust를 확립 |

reference validator가 `PASS`를 반환하거나 approval object가 schema/binding validation을 통과했다는 사실은 **`AUTHORIZED`라는 identity/organization 판단을 뜻하지 않는다.** producer와 issuer authority, transport, replay store, 실제 interception은 higher-authority runtime 책임이다.

### Enforcement flow

```text
user/task
    ↓
planner
    ↓
canonical planned operations
    ↓
runtime/tool adapter intercepts imminent action
    ↓
independently observed actual operation
+ resources + targets + environment + raw exposure facts
    ↓
runtime action assertion
    ↓
policy engine/reference validator
    ↓
Effect × Exposure → gate + action digest
    ↓
AUTO / guards / exact approval / protected override
    ↓
higher-authority issuer authentication
    ↓
atomic single-use consumption
    ↓
actual tool/API/action execution
```

action digest는 adapter가 imminent action을 관찰하고 assertion을 확정한 **뒤**, approval/override를 요청하기 **전에** 계산한다. 이후 operation, target, environment, exposure facts, semantic details 또는 actual action이 달라지면 digest와 nonce를 새로 만들고 과거 approval/override를 재사용하지 않는다.

`command.execute` 같은 opaque runtime operation으로 모든 shell command를 통과시키지 않는다. operation을 canonical semantics로 충분히 분류할 수 없거나 required target/fact가 없으면 enforced surface에서는 fail-closed한다.

### Minimal end-to-end example — external message

아래는 실제 메시지를 보내지 않는 conceptual integration example이다.

1. planner가 `external.message_send`를 planned operation으로 선언한다.
2. runtime adapter가 실제 send API 호출 직전에 이를 intercept하고, `actual_operations=["external.message_send"]`, recipient target, `environment=external`, raw exposure facts와 새 execution nonce를 독립적으로 구성한다.
3. policy engine이 assertion을 평가한다. 예를 들어 service credential이 포함된 외부 메시지는 operation floor L3와 Exposure X2가 되어 `REQUIRE_EXPLICIT_APPROVAL`이며, 현재 assertion에 대한 action digest가 생성된다.
4. higher-authority approval service가 human/organization issuer를 **별도로 인증한 뒤**, operation·target·environment·correlation ID·nonce·action digest에 정확히 결박된 approval assertion을 발급한다.
5. runtime은 approval의 schema/binding/expiry를 검증하고 shared ledger에서 approval identity와 nonce를 원자적으로 한 번 소비한다.
6. consumption이 성공한 경우에만 interceptor가 보류했던 send API를 실제 실행한다.
7. 같은 approval과 nonce를 다시 제출하면 ledger가 replay로 거부하고 두 번째 메시지는 실행하지 않는다.

이 예제에서 reference validator는 3번과 5번의 policy/binding 판단을 구현하는 기준이 될 수 있지만, 1) 실제 send call interception, 2) adapter producer/transport 인증, 3) issuer authority 인증, 4) production-grade shared atomic ledger, 5) 최종 tool dispatch 차단은 소비 runtime이 제공해야 한다.

같은 흐름을 실제 reference code로 실행하려면 **source repository checkout**의 `examples/runtime-adapter/mock_runtime.py`를 사용한다. source-only 예제이며 canonical consumer/release bundle에 포함되는 runtime adapter라고 간주하지 않는다. 이 예제는 외부 시스템을 호출하지 않고 첫 approval consumption은 성공하고 동일 approval replay는 차단되는 것을 검증한다.

### Fail-closed conditions

Profile C라고 주장하는 intercepted surface에서는 다음을 통과시키지 않는다.

- unknown/non-canonical 또는 plan 밖 actual operation
- 지원되지 않거나 의미를 충분히 분류할 수 없는 imminent action
- required target/environment/raw fact/semantic detail 누락
- 신뢰할 수 없는 adapter producer 또는 transport
- 필요한 approval/override의 issuer authority 또는 exact binding 불일치
- 만료된 approval/override, nonce/digest mismatch 또는 replay
- atomic ledger 장애로 single-use consumption 성공을 확정할 수 없음

## Task-scoped policy context and operation extensions

긴 정책 문서를 매 작업에 그대로 주입하는 대신 `--compiled-policy`를 사용하면 canonical source의 always-on invariant, operation summary와 관련 primary-owner prose만 deterministic하게 조합한다. completion-report subsection은 task context에서 제외되며 machine output은 extension의 logical namespace/digest를 사용하므로 동일 semantics가 filesystem 절대경로에 따라 바뀌지 않는다.

조직별 extension은 `OPERATION_EXTENSION.schema.json`, adapter capability는 `ADAPTER_CAPABILITIES.schema.json`을 따른다. Extension의 `supported_adapters`는 allowlist이고, 실제 runtime support는 별도 capability declaration이 exact operation을 포함해야 한다. 두 조건 중 하나라도 없으면 fail-closed한다.

Extension/capability digest match는 **integrity evidence**다. 조직 authority를 인증하지 않는다. Profile A/B에서는 local 문서를 `UNVERIFIED` integrity 상태로 inspect/validate할 수 있지만, Profile C의 production/public/external extension execution에서는 higher-authority channel이 제공한 expected extension/capability digest와의 `MATCHED` 상태가 필요하다. 그 expectation의 조직 권한과 transport 신뢰는 integrating runtime 책임이다.

상세 contract, CLI와 trust/capability vocabulary는 [extensions.md](extensions.md)를 따른다. source repository의 `examples/runtime-adapter/sandbox_artifact_adapter.py`는 capability 확인 → boundary → approval exact binding → atomic consume → local sandbox write를 보여주는 reference이며 production identity/transport/interception을 제공하지 않는다.

## Production checklist

published immutable Release가 없는 상태에서 만든 source-built ZIP은 official production release로 취급하지 않는다. release pipeline이 존재하는 것과 실제 trusted release가 존재하는 것은 별개다. official Release를 사용할 수 있는 production에서는 immutable Release + provenance verification 경로를 우선한다.

production에서 C를 사용하려면 최소 다음을 별도로 확인한다.

- adapter가 실제 side-effect surface를 빠짐없이 intercept하는가
- adapter assertion source와 transport가 spoofing되지 않는가
- production target/environment가 runtime에서 독립적으로 관찰되는가
- raw exposure facts의 출처가 신뢰 가능한가
- approval/override issuer authority가 조직 identity와 연결되는가
- approval/override consumption store가 atomic하고 shared-runtime replay를 막는가
- immutable release/provenance verification이 deployment 전에 수행되는가
- logs에 secret, credential, protected payload가 남지 않는가
- adapter가 지원하지 못하는 action은 명시적으로 fail-closed 또는 non-enforced로 분류되는가
- emergency/rollback도 기존 tag/approval을 재사용하지 않고 새 action identity를 갖는가

## Minimal project layouts

아래 layout은 profile별 **conceptual minimum**을 보여준다. official consumer ZIP의 physical file set을 profile마다 잘라 설치하라는 뜻이 아니며, 실제 consumer artifact는 모든 profile에 같은 full `.agent-policy/` bundle을 제공한다.

### A — Guidance

```text
project/
├── AGENTS.md
└── .agent-policy/
    ├── AGENTS.md
    ├── POLICIES.md
    └── PROJECT.md
```

### B — Validated

```text
project/
├── AGENTS.md
├── .github/workflows/policy-validation.yml
└── .agent-policy/
    ├── AGENTS.md
    ├── POLICIES.md
    ├── PROJECT.md
    ├── POLICY_CONTRACT.json
    ├── *.schema.json
    ├── requirements.lock
    └── scripts/
```

### C — Enforced Runtime

```text
project/
├── AGENTS.md
├── runtime-adapter/              # project/vendor integration
└── .agent-policy/
    ├── POLICY_CONTRACT.json
    ├── RUNTIME_ACTION.schema.json
    ├── APPROVAL_ASSERTION.schema.json
    ├── PROTECTED_OVERRIDE.schema.json
    └── scripts/
```

C의 `runtime-adapter/`는 이 bundle이 자동 생성하는 표준 경로가 아니다. 실제 vendor/runtime integration 위치를 프로젝트 convention에 맞게 둔다.

## Claims language

다음 표현을 구분한다.

- A: "policy guidance is installed"
- B: "policy bundle/readiness/risk calculation is validated"
- C: "the configured runtime boundary enforces supported intercepted actions"

A를 "enforced", B를 "runtime-enforced"라고 부르지 않는다. C에서도 adapter가 intercept하지 못하는 surface까지 통제한다고 과장하지 않는다.
