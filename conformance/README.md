# Language-neutral conformance suite

이 디렉터리는 `universal-agent-docs`의 machine-enforceable semantics를 Python 구현 내부 API가 아니라 **JSON wire corpus**로 고정한다. TypeScript, Go, Rust, Java 또는 다른 구현체는 repository Python 코드를 import하지 않고 `POLICY_CONTRACT.json`과 이 디렉터리의 JSON 파일만 읽어 같은 normative 결과를 만들 수 있어야 한다.

## Files

- `golden.json`: 정상/허용 경계와 deterministic relation vector
- `invalid.json`: 반드시 fail-closed하거나 invalid로 판정해야 하는 vector
- `corpus.schema.json`: 두 corpus 파일의 JSON Schema
- `result.schema.json`: 구현체가 반환할 aggregate result JSON 형식
- `coverage.json`: 필수 semantic coverage와 현재 operation catalog의 직접 coverage/exemption ledger
- `scripts/conformance.py`: Python reference implementation runner. corpus의 Source of Truth가 아니며 비교 기준 구현일 뿐이다.

`POLICY_CONTRACT.json`이 정책 의미의 normative owner다. corpus는 그 의미를 대표 fixture로 고정하며 contract와 충돌할 경우 contract를 먼저 해석하고 corpus/구현을 함께 수정한다.

## Corpus format v2

각 corpus는 다음 envelope을 가진다.

```json
{
  "format": "universal-agent-docs-conformance-v2",
  "schema_version": 2,
  "policy_schema_version": 16,
  "vectors": []
}
```

각 vector는 최소 다음 필드를 가진다.

```json
{
  "id": "stable-lowercase-id",
  "description": "human explanation",
  "category": "routing",
  "kind": "routing",
  "covers": ["routing.canonical_resolution"],
  "input": {},
  "expected": {},
  "normative_fields": ["/routing_status"],
  "notes": "optional non-normative note"
}
```

`expected` 전체를 exact-match하지 않는다. `normative_fields`의 JSON Pointer만 비교한다. 따라서 diagnostic 문자열, 경로, stack trace, warning wording처럼 implementation-specific인 출력은 호환성 기준이 아니다. `/errors`와 `/warnings` 자체를 normative exact-match field로 사용하지 않는다.

지원 `kind`의 **authoritative 목록은 `corpus.schema.json`의 `properties.vectors.items.properties.kind.enum`**이다. README에는 그 enum의 수동 exhaustive copy를 유지하지 않는다. Python reference runner의 `RUNNERS` registry는 이 schema enum과 exact parity를 가져야 하며 테스트가 이를 검증한다.

각 kind의 `input`은 JSON data만 사용한다. approval/override fixture의 `$ACTION_DIGEST`, `$CORRELATION_ID`, `$EXECUTION_NONCE`, `$ACTUAL_OPERATIONS`, `$TARGETS`, `$ENVIRONMENT` 토큰은 같은 vector의 execution-boundary 결과로 치환하는 language-neutral fixture token이다.

시간 의존 vector는 `reference_time`을 명시하며 wall clock을 normative input으로 사용하지 않는다. replay vector는 fresh temporary atomic ledger에서 첫 consumption과 동일 객체의 두 번째 consumption을 순서대로 수행한다.

distribution vector의 archive entry는 `name`, 선택적 `type`(`file` 또는 `symlink`), `data` 또는 `repeat_byte` + `size`로 표현한다. 구현체는 실제 ZIP/container 형식으로 materialize한 뒤 **추출 전에** 동일한 archive safety semantics를 평가해야 한다.

## Result protocol

구현체는 전체 suite 실행 결과를 `result.schema.json` 형식의 단일 JSON object로 반환하는 것을 기본 protocol로 사용한다.

```json
{
  "format": "universal-agent-docs-conformance-result-v1",
  "suite_schema_version": 2,
  "policy_schema_version": 16,
  "implementation": {
    "name": "my-policy-engine",
    "version": "1.2.3",
    "language": "go"
  },
  "summary": {"total": 1, "passed": 1, "failed": 0},
  "results": [
    {
      "id": "routing-canonical-plan-enforcement",
      "status": "PASS",
      "actual": {},
      "mismatches": []
    }
  ]
}
```

streaming/CI integration이 필요하면 동일 case result object를 vector당 한 줄로 출력하는 JSON Lines도 허용한다. aggregate result가 canonical interchange format이고 JSONL은 transport convenience다.

위 JSON은 protocol shape를 설명하는 최소 예시이며 현재 corpus의 총 vector 수를 고정하는 문서가 아니다. 실제 count는 `python scripts/conformance.py --coverage` 또는 aggregate result의 `summary`를 사용한다.

## Running the Python reference implementation

```bash
python scripts/conformance.py
python scripts/conformance.py --coverage
python scripts/conformance.py --jsonl
python scripts/conformance.py --output /tmp/uad-conformance-result.json
```

CI에서는 unit test와 별도로 reference runner 전체를 독립 실행한다.

```bash
python -m unittest tests.test_conformance -v
python scripts/conformance.py
```

## Implementing in another language

외부 구현체는 다음 순서만 필요하다.

1. `POLICY_CONTRACT.json`, `golden.json`, `invalid.json`, `corpus.schema.json`, `result.schema.json`, `coverage.json`을 읽는다.
2. corpus envelope과 vector를 `corpus.schema.json`으로 검증한다.
3. vector `kind`별 입력을 자신의 policy engine/runtime adapter에 전달한다.
4. `expected` 전체가 아니라 `normative_fields` JSON Pointer만 비교한다.
5. 모든 vector ID에 대해 result를 만들고 `result.schema.json`을 만족하는 aggregate JSON을 출력한다.
6. `coverage.json`의 `required_semantics`가 vector의 `covers` union에 포함되는지 확인한다.
7. operation catalog의 모든 ID가 직접 vector input에서 사용되거나 `operation_exemptions`에 명시돼 있는지 확인한다. 새 operation이 추가되면 direct coverage 또는 명시적 exemption 없이는 suite coverage check가 실패해야 한다.

Python exception class, 함수 이름, diagnostic 문자열은 protocol이 아니다.

## Stable vector policy

vector `id`는 public compatibility identifier로 취급한다. 기존 ID를 다른 의미로 재사용하지 않는다. 의미가 추가되면 새 ID를 추가한다. 기존 normative meaning을 제거해야 한다면 corpus schema/version 변경 또는 명시적인 migration을 동반한다. typo/description/notes 수정처럼 normative input·expected·normative_fields를 바꾸지 않는 편집은 ID를 유지할 수 있다.

vector 삭제는 해당 semantic이 contract에서 제거되거나 새 stable vector로 명시적으로 supersede되는 경우에만 허용한다. operation rename은 contract의 lifecycle 규칙과 동일하게 새 canonical ID/vector 추가 후 기존 의미의 migration을 명시한다.

## Direct high-risk operation evidence

공통 invariant만으로 adapter 지원을 주장하지 않는다. 현재 direct vectors는 우선순위가 높은 database, Git state mutation, credential/IAM, external side effect, cloud mutation/delete, data export operation을 직접 입력에 포함한다. direct vector가 없는 operation은 `coverage.json`의 구체적 exemption을 유지해야 하며, exemption은 adapter support 인증을 의미하지 않는다.

## Extension and capability contract

`OPERATION_EXTENSION.schema.json`과 `ADAPTER_CAPABILITIES.schema.json`은 Python 구현 밖에서도 소비할 수 있는 wire contract다. corpus의 `extension_contract` / `extension_boundary` kind는 namespace 충돌, deterministic digest, integrity expectation, bilateral adapter capability, production fail-closed, extension Effect/Exposure semantics를 normative fields로 검증한다. Digest match는 authority 인증으로 해석하지 않는다.

## Coverage scope

suite는 모든 operation을 하나씩 인증하려는 목록이 아니다. Effect/Exposure/gate/lifecycle 특성이 다른 operation family와 중요한 trust boundary를 대표한다. 직접 vector가 없는 현재 operation은 `coverage.json`에 exemption reason이 있어야 하며, 이는 해당 operation이 구현체에서 지원된다고 인증하는 의미가 아니다.

현재 corpus는 routing authority, unknown/deprecated lifecycle, Effect floor와 production/context escalation, raw Exposure derivation, plan/actual mismatch, opaque runtime operation, hard action signature, target/environment constraints, action digest, approval/override binding과 replay, readiness states, archive safety, trust/release manifest integrity를 다룬다.

### Representative high-risk direct operation coverage

direct vector는 operation 이름이 corpus에 등장하는지만 확인하는 용도가 아니라, 해당 family에서 사고 영향이 큰 **서로 다른 machine semantics**를 고정하는 데 사용한다.

| Operation | Representative vector | 직접 검증하는 의미 |
|---|---|---|
| `cloud.resource_change` | `kubectl-delete-pod-is-bounded-change` | L3 external effect와 concrete target/gate |
| `cloud.resource_delete` | `terraform-destroy-is-cloud-delete` | destructive cloud delete의 L4 floor |
| `database.schema_change` | `production-database-schema-change-escalates-l4` | production에서 L3→L4 escalation + X2 approval |
| `database.destructive_change` | `regulated-database-destructive-change-requires-override` | L4 + regulated X3 → protected override gate |
| `credential.rotate` | `privileged-credential-rotation-requires-override` | privileged credential X3 + L4 override gate |
| `iam.change` | `organization-wide-iam-change-requires-override` | organization-wide blast radius X3 + L4 override gate |
| `external.message_send` | `external-message-send-requires-approval` | concrete external recipient에 대한 L3 approval gate |
| `service.restart` | `production-service-restart-escalates-l4` | production에서 L3→L4 escalation |
| `storage.object_delete` | `staging-storage-object-delete-is-l4` | storage delete의 L4 floor와 concrete object target |
| `network.configuration_change` | `production-network-configuration-change-escalates-l4` | production에서 L3→L4 escalation |
| `artifact.publish` | `public-artifact-publish-escalates-l4` | public destination context에서 L3→L4 escalation |

`git.merge`와 `git.rebase`도 우선 검토했지만 현재 contract에서 둘은 L2이고 schema v16에 operation-specific production/context escalation 또는 semantic-detail requirement가 없다. 따라서 이번 high-risk direct set에서는 shared Git/runtime invariant exemption을 유지한다. **exemption은 adapter support 인증이 아니며**, 해당 operation 지원을 주장하려면 direct vector를 추가해야 한다.

