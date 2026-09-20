# Adoption profiles and quick start

`universal-agent-docs`는 하나의 "보안 모드"가 아니라, 같은 policy bundle을 어디까지 실제 runtime에 연결했는지에 따라 보장이 달라지는 도입 경로를 제공한다. 이 문서의 profile 이름은 **도입 설명을 위한 문서 분류**이며 `POLICY_CONTRACT.json`의 machine-enforceable state가 아니다.

## Profiles at a glance

| Profile | 목적 | 제공하는 보장 | 제공하지 않는 보장 |
|---|---|---|---|
| **A — Guidance** | 개발 에이전트에게 일관된 지침과 프로젝트 사실 제공 | agent instruction hierarchy, human-readable policy, project fact discipline | tool interception, actual-operation verification, approval enforcement, replay protection |
| **B — Validated** | policy bundle과 계획/위험 판정을 자동 검증 | bundle/schema validation, readiness, canonical routing, Effect/Exposure/gate calculation, distribution integrity | trusted actual-operation assertion이 없으면 실행 차단 보장 없음; schema-valid runtime payload만으로 producer authenticity 보장 없음 |
| **C — Enforced Runtime** | 실제 action/tool boundary에서 fail-closed enforcement | trusted runtime adapter, actual-vs-planned check, action digest, approval/override exact binding, replay protection, provenance verification | vendor/runtime이 intercept하지 못하는 side effect까지 자동 통제한다는 보장 없음; issuer/adapter trust는 higher-authority integration이 확립해야 함 |

Profile은 누적적이다. C는 B와 A의 기반을 포함한다.

## Which profile should I use?

다음 중 가장 먼저 "예"가 되는 질문을 선택한다.

1. **에이전트가 저장소 규칙과 프로젝트 사실을 일관되게 읽게 하는 것만 필요한가?** → A
2. **CI에서 bundle/readiness/routing/risk/integrity를 자동 검증하고 싶은가?** → B
3. **실제 shell/tool/API 호출 직전에 allow/block/approval/override를 강제해야 하는가?** → C

production, customer data, privileged credentials, external/public side effects를 자동 실행하는 환경에서는 C가 목표 상태다. A/B만 사용하는 동안에는 해당 runtime이 스스로 실행을 차단한다고 주장하지 않는다.

## Minimal consumer installation

공식 source bundle을 소비 프로젝트 root에 그대로 overlay하지 않는다. consumer ZIP을 staging 위치에 푼 뒤 `.agent-policy/`와 생성된 root `AGENTS.md`를 프로젝트에 적용한다.

Upstream checkout에서 consumer artifact를 만드는 예:

```bash
python -m pip install --require-hashes --requirement requirements.lock
python scripts/package_consumer.py --output-dir dist
python -m zipfile -e dist/universal-agent-docs-consumer.zip /tmp/uad-consumer
```

staging tree:

```text
/tmp/uad-consumer/
└── universal-agent-docs-consumer/
    ├── AGENTS.md
    └── .agent-policy/
        ├── AGENTS.md
        ├── POLICIES.md
        ├── PROJECT.md
        ├── POLICY_CONTRACT.json
        └── ...
```

소비 프로젝트에 적용할 때:

1. `.agent-policy/`가 이미 있으면 덮어쓰지 말고 기존 설치와 version/provenance를 먼저 확인한다.
2. root `AGENTS.md`가 없으면 generated router를 복사할 수 있다.
3. root `AGENTS.md`가 이미 있으면 **자동 overwrite하지 않는다**. 두 instruction hierarchy를 사람이 읽고 기존 프로젝트 지침을 보존한 상태에서 policy router 링크를 병합한다.
4. vendored `.agent-policy/PROJECT.md`는 template이므로 그대로 두고 readiness PASS를 기대하지 않는다. bootstrap candidate를 만든 뒤 evidence를 검토해 프로젝트 사실을 채운다.

consumer contract는 `overwrite_existing_root_agents=false`와 `extraction_requires_collision_check=true`를 명시한다. 일반 unzip/copy 도구가 이 규칙을 대신 강제해 준다고 가정하지 않는다.

## PROJECT bootstrap → review → readiness

소비 프로젝트 root에서 실행한다.

```bash
python .agent-policy/scripts/validate.py \
  --bootstrap-project . \
  --bootstrap-output ./PROJECT.candidate.md
```

bootstrap은 관찰 가능한 source root, command source, runtime source, component 후보를 수집하지만 모든 자동 발견 fact를 `Inferred`로 남긴다. `Confirmed`로 자동 승격하지 않는다.

다음 순서를 따른다.

1. `PROJECT.candidate.md`를 실제 source/config와 대조한다.
2. 맞는 fact만 `Confirmed`로 승격하고 검증 가능한 `path:`, `command-source:`, `value-source:` evidence를 연결한다.
3. 실제 project-facts 위치에 반영한다. 기본 consumer layout에서는 `.agent-policy/PROJECT.md`가 template 출발점이다.
4. development readiness를 실행한다.

```bash
python .agent-policy/scripts/validate.py \
  --project-root . \
  --readiness development
```

deploy까지 자동화한다면:

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

B에서는 canonical plan, Effect/Exposure, gate를 계산하고 malformed/unknown policy input을 fail-closed할 수 있다. 그러나 **trusted runtime/tool adapter가 실제 호출을 독립적으로 보고하지 않는다면 계산된 gate가 실제 side effect를 막는다는 보장은 없다**.

`RUNTIME_ACTION.schema.json`을 만족하는 JSON을 받았다는 사실만으로 adapter producer identity나 transport integrity가 확립되는 것도 아니다.

### Upgrade to C

실제 tool/action boundary에 adapter를 연결하고 trusted assertion source, exact action binding, single-use ledger, higher-authority issuer authentication을 구성한다.

## Profile C — Enforced Runtime

### Required pieces

B에 더해 최소 다음이 필요하다.

- 실제 tool/action을 intercept하는 runtime adapter 또는 equivalent trusted boundary
- independently derived `actual_operations`
- affected resources, concrete targets, environment, raw exposure facts
- unique correlation ID와 single-use execution nonce
- action digest 계산
- explicit approval assertion + atomic replay ledger
- protected override assertion + atomic replay ledger
- adapter producer/transport trust
- release/provenance verification
- fail-closed handling for unknown/unclassifiable operations

### Enforcement flow

```text
planned canonical operations
        ↓
trusted runtime observes imminent action
        ↓
actual operations + resources + targets + environment + exposure facts
        ↓
execution boundary → Effect × Exposure → gate + action digest
        ↓
AUTO / guards / exact approval / protected override
        ↓
atomic consume → tool execution
```

`command.execute` 같은 opaque runtime operation으로 모든 shell command를 통과시키지 않는다. 의미를 구체 operation으로 분류할 수 없으면 fail-closed하는 것이 기본이다.

approval/override schema validation만으로 issuer authority를 확립하지 않는다. 실제 production enforcement에서는 조직/runtime의 higher-authority identity/authorization mechanism이 issuer와 adapter transport를 인증해야 한다.

## Production checklist

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
