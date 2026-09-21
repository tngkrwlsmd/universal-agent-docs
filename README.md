# universal-agent-docs

`universal-agent-docs`는 개발 에이전트의 계획·실행·위험·승인을 공통 vocabulary로 표현하고 검증하기 위한 **vendor-neutral policy contract + reference validator + conformance suite**다.

문서만 읽히게 하는 것부터 실제 runtime enforcement를 통합하는 것까지 같은 bundle을 단계적으로 사용할 수 있다.

## 30초 요약

| 질문 | 답 |
|---|---|
| **무엇을 제공하나?** | agent instruction hierarchy, human policy, canonical operation/risk contract, Python reference validator, JSON wire schemas, language-neutral conformance corpus |
| **무엇을 제공하지 않나?** | 모든 shell/tool/API를 자동으로 가로채는 범용 runtime, 조직 identity/authz, trusted transport, production replay ledger, 특정 vendor용 완성 adapter |
| **어떻게 도입하나?** | A(Guidance) → B(Validated) → C(Enforced Runtime) 중 필요한 보장 수준까지 연결한다. |
| **machine semantics의 Source of Truth는?** | `POLICY_CONTRACT.json` |
| **사람용 정책 설명의 primary owner는?** | `POLICIES.md` |

> **Release channel:** Production adoption에는 최신 immutable SemVer Release를 우선한다. `main`에는 아직 Release되지 않은 변경이 있을 수 있으므로 source checkout은 unreleased 변경을 평가할 때 사용한다.

## 5분 Quick Start

처음 도입할 때 내부 schema나 runtime contract를 모두 이해할 필요는 없다. A/B/C는 **동일한 full `.agent-policy/` bundle**을 사용하며 Canonical onboarding은 하나다.

```text
install → bootstrap → human review → validate → optional runtime integration
```

| 처음 묻는 질문 | 답 |
|---|---|
| **무엇을 설치하나?** | Release의 `universal-agent-docs-consumer.zip` 안 `.agent-policy/` bundle |
| **무엇을 직접 수정하나?** | project-owned root `AGENTS.md` router 병합과 `.agent-policy/PROJECT.md`의 project facts |
| **Profile A/B는 어떻게 구분하나?** | 지침만 연결하면 A, validator로 readiness/routing을 자동 검증하면 B |

설치 후 파일 ownership도 단순하게 본다.

| 경로 | 기본 owner | 규칙 |
|---|---|---|
| root `AGENTS.md` | consumer project | 기존 지시를 보존하고 universal policy router만 사람이 병합한다. 자동 overwrite하지 않는다. |
| `.agent-policy/PROJECT.md` | consumer project | 실제 repository facts와 evidence를 사람이 검토해 유지한다. |
| 그 외 `.agent-policy/` | upstream bundle | 임의 편집보다 새 Release로 교체한다. 조직별 확장은 공식 extension/capability contract를 사용한다. |

### 1. Install

가능하면 [GitHub Releases](https://github.com/tngkrwlsmd/universal-agent-docs/releases)의 최신 immutable SemVer Release에서 `universal-agent-docs-consumer.zip`을 받아 프로젝트의 `.agent-policy/`로 설치한다. Unreleased `main` 평가가 아니라면 source checkout에서 직접 만든 ZIP을 production provenance의 대체물로 취급하지 않는다.

Source checkout 자체를 평가해야 할 때만 다음을 사용한다.

```bash
git clone https://github.com/tngkrwlsmd/universal-agent-docs.git
cd universal-agent-docs
python -m pip install --require-hashes --requirement requirements.lock
python scripts/package_consumer.py --output-dir dist
```

### 2. Bootstrap → human review

소비 프로젝트에서 conservative candidate를 만든다.

```bash
python .agent-policy/scripts/validate.py --bootstrap-project . --bootstrap-output PROJECT.candidate.md
```

Bootstrap 결과는 `Inferred`/`Unknown` 후보일 뿐 자동 `Confirmed`가 아니다. source/config/evidence와 대조해 맞는 값만 `.agent-policy/PROJECT.md`에 반영한다.

이 시점까지 정책 지침을 읽히는 용도로만 사용하면 **Profile A — Guidance**다.

### 3. Validate

```bash
python .agent-policy/scripts/validate.py --project-root . --readiness development
python .agent-policy/scripts/validate.py --routing-mode enforcement --route "run tests" --operation test.execute
```

필요한 policy context만 만들려면:

```bash
python .agent-policy/scripts/validate.py --compiled-policy --operation code.modify --resource src/auth/login.py
```

Bundle/readiness/routing/risk를 자동 검증하면 **Profile B — Validated**다. `documented=PASS` 또는 `evidence_verified=PASS`는 build/test/deploy command의 실제 성공을 뜻하지 않으며 기본 `execution_verified`는 `NOT_RUN`이다.

### 4. Optional runtime integration

실제 tool/API/action 직전에 allow/block/approval/override를 집행해야 하면 **Profile C — Enforced Runtime**으로 확장한다. Planner와 독립적인 actual operation 관찰, concrete target/environment/exposure facts, exact approval/override binding, atomic replay consumption, issuer/transport trust와 final dispatcher가 필요하다. Bundle 설치나 `--routing-mode enforcement`만으로 Profile C가 되지 않는다.

상세 설치·PROJECT bootstrap/readiness·A→B→C upgrade 절차의 primary owner는 [Adoption profiles](docs/adoption-profiles.md)다. 작은 before/after 흐름은 [Profile A/B consumer example](examples/consumer-basic/README.md), 신뢰 경계는 [Threat model](docs/threat-model.md), 실행 형태는 [runtime adapter examples](examples/runtime-adapter/README.md)를 따른다.

## 어떤 Profile을 써야 하나?

| Profile | 필요한 경우 | 이 저장소가 제공하는 것 | 추가 integration 필요 |
|---|---|---|---|
| **A — Guidance** | 에이전트에게 일관된 규칙과 project facts를 읽히고 싶다 | `AGENTS.md`, `POLICIES.md`, consumer `PROJECT.md` discipline | runtime 차단 없음 |
| **B — Validated** | CI에서 routing/risk/readiness/integrity를 검증하고 싶다 | A + validator, Effect/Exposure/gate 계산, distribution/conformance validation | actual tool 호출 interception 없음 |
| **C — Enforced Runtime** | 실제 side effect 직전에 allow/block/approval/override를 강제해야 한다 | B + runtime/approval/override contract와 reference semantics | trusted adapter/interceptor, issuer authz, transport, shared replay ledger, final dispatcher |

A/B/C는 서로 다른 ZIP이 아니라 같은 bundle을 **어디까지 실제 runtime에 연결했는가**의 차이다.

## 문서 지도

| 문서 | Primary responsibility |
|---|---|
| [README.md](README.md) | landing page / orientation |
| [docs/adoption-profiles.md](docs/adoption-profiles.md) | consumer installation, PROJECT bootstrap/readiness, A/B/C adoption |
| [docs/extensions.md](docs/extensions.md) | operation extension, adapter capability, integrity/authority boundary |
| [docs/threat-model.md](docs/threat-model.md) | Profile C trust boundary, threat, residual risk와 integration responsibility |
| [evaluation/README.md](evaluation/README.md) | non-normative practical evaluation corpus와 품질 지표 |
| [conformance/README.md](conformance/README.md) | language-neutral conformance protocol |
| [AGENTS.md](AGENTS.md) | 항상 읽는 작은 root router와 공통 invariant |
| [POLICIES.md](POLICIES.md) | human-facing policy rationale/procedure |
| `templates/PROJECT.md` | canonical source template for consumer project facts; root `PROJECT.md` is a compatibility mirror |
| [POLICY_CONTRACT.json](POLICY_CONTRACT.json) | machine-enforceable semantics의 normative Source of Truth |
| [docs/generated-policy-reference.md](docs/generated-policy-reference.md) | `POLICY_CONTRACT.json`의 generated non-normative reference |

같은 절차를 여러 문서에서 독립적으로 소유하지 않는다. Machine-enforceable contract와 human-facing policy가 enforcement 의미에서 충돌하면 어느 한쪽을 임의로 우선해 통과시키지 말고 함께 수정한다.

## Repository map

```text
universal-agent-docs/
├── AGENTS.md
├── POLICIES.md
├── PROJECT.md                 # compatibility mirror
├── templates/
│   └── PROJECT.md             # canonical source template
├── POLICY_CONTRACT.json
├── POLICY_CONTRACT.schema.json
├── OPERATION_EXTENSION.schema.json
├── ADAPTER_CAPABILITIES.schema.json
├── RUNTIME_ACTION.schema.json
├── APPROVAL_ASSERTION.schema.json
├── PROTECTED_OVERRIDE.schema.json
├── docs/
│   ├── adoption-profiles.md
│   ├── extensions.md
│   ├── threat-model.md
│   └── generated-policy-reference.md
├── examples/
│   ├── consumer-basic/
│   ├── extensions/
│   ├── capabilities/
│   └── runtime-adapter/
├── conformance/
├── evaluation/
├── scripts/
│   ├── validate.py
│   ├── conformance.py
│   ├── evaluate.py
│   ├── policy_diff.py
│   ├── benchmark.py
│   ├── package.py
│   ├── package_consumer.py
│   └── validation/
├── tests/
└── .github/workflows/
```

Canonical source template은 `templates/PROJECT.md`다. Root `PROJECT.md`는 기존 source/validator compatibility를 위해 byte-for-byte mirror로 유지하고, consumer artifact에서는 이 template content가 `.agent-policy/PROJECT.md`로 제공된다.

## Extension과 capability

조직/vendor 전용 operation은 core catalog를 수정하지 않고 `OPERATION_EXTENSION.schema.json`으로 추가할 수 있다. Extension의 `supported_adapters`는 allowlist일 뿐 실제 capability 증명이 아니다. Runtime에서 extension operation을 사용하려면 `ADAPTER_CAPABILITIES.schema.json`을 따르는 별도 adapter capability declaration이 exact operation을 지원해야 한다.

Schema validity, integrity, capability, authority는 서로 다른 보장이다. 상세 contract와 production trust boundary는 [docs/extensions.md](docs/extensions.md)를 따른다.

## Language-neutral conformance

`conformance/`는 Python 내부 API가 아니라 JSON corpus/schema/result protocol로 machine semantics를 고정한다. Source tree의 dependency-free JavaScript core evaluator는 Python을 호출하지 않고 routing/execution-boundary/catalog vector를 독립 계산해 cross-language 구현 가능성을 검증한다. 이는 전체 대체 runtime을 제공한다는 뜻은 아니다.

Protocol과 구현 절차의 primary owner는 [conformance/README.md](conformance/README.md)다.

## Source repository 개발

Source checkout 자체를 수정할 때의 기본 검증:

```bash
python -m pip install --require-hashes --requirement requirements.lock
python scripts/generate_policy_reference.py --check
python scripts/validate.py
python -m unittest discover -s tests -v
python scripts/conformance.py
python scripts/conformance.py --coverage
node conformance/reference-javascript/runner.mjs
python scripts/evaluate.py --fail-on-mismatch
```

Conformance는 normative semantics의 구현 정합성이고 `evaluation/`은 representative real-world routing/gate 품질 측정이다. 둘을 같은 PASS 의미로 취급하지 않는다. Policy contract upgrade 영향을 비교하려면 `python scripts/policy_diff.py <before.json> <after.json>`을 사용한다. JSON Schema required-field 변화까지 보려면 `--before-schema`와 `--after-schema`를 함께 넘긴다. 또한 정책 적용 비용 baseline은 `python scripts/benchmark.py --static-only --json`으로 측정할 수 있다. Timing benchmark는 환경 의존 값이므로 기본 CI threshold로 사용하지 않는다.

CI는 Linux/macOS/Windows × Python 3.10/3.14에서 bundle validation, tests, conformance, practical evaluation, canonical/consumer distribution build와 verification을 수행한다.

Release는 `.github/workflows/release.yml`의 SemVer tag flow를 사용하며 immutable Release와 provenance verification을 우회하지 않는다. Canonical source artifact 이름은 `universal-agent-docs.zip`, consumer artifact 이름은 `universal-agent-docs-consumer.zip`이다.

## 설계 불변조건

- `POLICY_CONTRACT.json`의 machine semantics와 `POLICIES.md`의 human policy ownership을 구분한다.
- 계획한 operation과 runtime에서 실제 관찰된 operation을 구분한다.
- Effect와 Exposure를 별도로 계산하고 gate를 결정한다.
- schema-valid payload만으로 identity/organization authority를 주장하지 않는다.
- approval/override는 exact action에 결박하고 replay를 single-use로 다룬다.
- 실행하지 않은 검증을 `PASS`, 확인하지 않은 사실을 `VERIFIED`라고 표현하지 않는다.
- 기존 consumer layout과 contract compatibility를 이유 없이 깨지 않는다.

## License

Apache License 2.0. 자세한 내용은 [LICENSE](LICENSE)를 따른다.
