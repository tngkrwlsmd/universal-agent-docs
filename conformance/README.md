# Language-Neutral Conformance Suite

이 디렉터리는 `universal-agent-docs`의 normative semantics를 Python 구현에 종속되지 않은 JSON corpus로 제공한다. TypeScript, Go, Rust, Java 등 외부 구현체는 저장소의 Python 코드를 import하지 않고도 `POLICY_CONTRACT.json`과 이 디렉터리의 JSON 파일만 읽어 동일한 결과를 산출할 수 있다.

## Files

- `suite.json`: canonical conformance corpus. 새 구현체가 소비해야 하는 주 입력이다.
- `schema.json`: `suite.json`의 JSON Schema.
- `result.schema.json`: 구현체가 반환해야 하는 result protocol의 JSON Schema.
- `reference_runner.py`: Python validator를 이용한 reference implementation. corpus의 normative owner가 아니라 검증용 oracle이다.
- `golden.json`, `invalid.json`: v1 compatibility corpus. 기존 vector ID는 `suite.json`에서도 유지된다.

Normative policy semantics의 최종 Source of Truth는 계속 `POLICY_CONTRACT.json`이다. Conformance corpus는 그 contract를 대표 사례로 고정하며 contract와 충돌할 경우 contract를 수정하거나 corpus를 함께 갱신해야 한다.

## Conformance version

`suite.json`의 `conformance_version`은 corpus/protocol 형식의 버전이다. 현재 버전은 **2**다. `contract_schema_version`은 이 suite가 대상으로 하는 `POLICY_CONTRACT.json` schema version과 정확히 일치해야 한다.

이 두 버전은 release SemVer와도 별개다.

## Case format

각 case는 다음 공통 필드를 가진다.

```json
{
  "id": "declared-exposure-cannot-lower",
  "description": "Declared exposure cannot lower raw-fact-derived exposure.",
  "category": "exposure",
  "kind": "execution_boundary",
  "input": {},
  "expected": {},
  "normative_fields": [
    "status",
    "effective_exposure",
    "action_gate"
  ]
}
```

- `id`: stable API다. 의미가 같은 case를 수정할 때 ID를 재사용하고, 의미가 달라지면 새 ID를 추가한다.
- `description`: 사람이 읽는 목적 설명이다.
- `category`: coverage grouping이다.
- `kind`: 구현체가 어떤 conformance operation을 실행해야 하는지 정의한다.
- `input`: language-neutral input fixture다.
- `expected`: normative expected result의 최소 subset이다.
- `normative_fields`: 반드시 비교해야 하는 result field 목록이다.
- `notes`: 선택적 설명이다.

구현체의 exception type, stack trace, 사람이 읽는 error/warning 문구는 normative 비교 대상이 아니다. 특히 `errors`와 `warnings` 문자열 exact match를 conformance requirement로 사용하지 않는다.

## Supported kinds

현재 v2 protocol은 다음 kind를 정의한다.

- `routing`: canonical operation resolution, alias, advisory/enforcement authority.
- `execution_boundary`: Effect/Exposure/gate, plan/runtime binding, target/environment, opaque operation, high-confidence action signature.
- `lifecycle`: canonical operation ID 존재 여부와 lifecycle 상태.
- `digest_relation`: exact digest 값 대신 두 action digest의 equality/inequality 관계를 검증한다.
- `approval`: exact binding, fixed reference time temporal validation, single-use replay.
- `override`: protected override exact binding과 replay.
- `readiness`: documented/evidence/execution readiness 상태.
- `distribution`: unsafe archive path, duplicate, casefold/Unicode collision, symlink, resource limit.
- `integrity`: trust/release manifest integrity.

Time-sensitive case는 `input.reference_time`을 명시한다. 구현체는 시스템 현재 시간이 아니라 그 값을 기준으로 temporal semantics를 평가해야 한다. Replay case는 case마다 새 빈 atomic consumption registry를 시작한 뒤 동일 assertion을 순서대로 두 번 소비한다.

## Result protocol

외부 구현체는 전체 suite 실행 후 다음 형태의 단일 JSON 객체를 반환해야 한다.

```json
{
  "conformance_version": 2,
  "implementation": {
    "name": "example-go-engine",
    "version": "0.3.0"
  },
  "summary": {
    "total": 73,
    "passed": 73,
    "failed": 0
  },
  "results": [
    {
      "id": "routing-canonical-operation-direct",
      "status": "PASS",
      "observed": {
        "routing_status": "PASS",
        "planned_canonical_operations": ["test.execute"]
      },
      "mismatches": []
    }
  ]
}
```

`observed`에는 해당 case의 `normative_fields`만 포함하는 것이 권장된다. 구현체 고유 diagnostic은 별도 로그에 출력할 수 있지만 result protocol의 normative comparison에는 사용하지 않는다.

## External implementation procedure

외부 구현체는 다음 순서로 suite를 실행하면 된다.

1. `POLICY_CONTRACT.json`을 읽고 지원하는 contract schema version인지 확인한다.
2. `conformance/schema.json`으로 `suite.json`을 검증한다.
3. `suite.contract_schema_version`이 contract의 `schema_version`과 같은지 확인한다.
4. 각 case의 `kind`에 해당하는 operation을 실행한다.
5. `normative_fields`만 `expected`와 비교한다.
6. 모든 case의 결과를 `result.schema.json` 형식으로 출력한다.
7. 하나라도 mismatch가 있으면 conformance run은 실패다.

Python code를 import할 필요는 없다. JSON Schema validator도 특정 library를 요구하지 않는다.

## Python reference runner

현재 repository의 Python validator를 reference implementation으로 실행하려면:

```bash
python conformance/reference_runner.py --check
```

전체 machine-readable result가 필요하면:

```bash
python conformance/reference_runner.py > conformance-result.json
```

또는:

```bash
python conformance/reference_runner.py --output conformance-result.json --check
```

CI에서는 reference runner를 일반 unit test와 별도로 실행한다.

## Operation coverage

모든 canonical operation을 독립 vector 하나씩 만들 필요는 없다. 대신 `operation_coverage_exemptions`가 coverage drift를 명시적으로 관리한다.

모든 operation ID는 반드시 다음 둘 중 하나여야 한다.

1. 하나 이상의 case의 `planned_operations` 또는 `actual_operations`에 직접 등장한다.
2. `operation_coverage_exemptions`에 rationale과 함께 명시된다.

새 operation을 contract에 추가하고 corpus/exemption을 갱신하지 않으면 coverage test가 실패한다. Deprecated operation은 exemption으로 넘길 수 없고 dedicated case가 필요하다.

## Stable ID and evolution policy

- 기존 case의 normative 의미가 유지되는 수정: 같은 ID 유지.
- 새로운 의미 또는 새로운 boundary: 새 ID 추가.
- case 삭제: conformance major-format migration이나 contract semantic removal과 함께 명시적으로 처리한다.
- expected normative semantics 변경: 관련 contract/schema 변화와 함께 review한다.
- diagnostic 문구 변경: vector 변경이 필요하지 않다.
- v1 `golden.json`/`invalid.json` ID는 v2 suite에서 계속 보존한다.

Corpus PASS는 구현체가 suite에 포함된 semantics를 만족한다는 뜻이지, 구현체가 모든 canonical operation을 실제 runtime에서 지원한다는 뜻은 아니다.
