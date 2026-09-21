# PROJECT.md — consumer project-facts template, architecture, readiness

> **Upstream repository note:** 이 루트 파일은 `universal-agent-docs` 자체의 운영 상태를 기록하는 문서가 아니라 consumer 프로젝트가 복사·검토해 채우는 template이다. 아래 `Unknown` 값은 upstream readiness 실패를 뜻하지 않는다.

이 파일은 `PROJECT_MAP.md`와 `ARCHITECTURE.md` 역할을 통합한 단일 프로젝트 지도다. 상세 제품 명세나 장기 계획을 복제하지 말고 실제 Source of Truth의 위치를 가리킨다.

**이 upstream 저장소의 `PROJECT.md`는 consumer 프로젝트가 채워 넣기 위한 template이다.** 따라서 `profile: "template"`과 Unknown fact가 남아 있는 것이 의도된 초기 상태이며, 이 파일 자체를 `universal-agent-docs` upstream의 readiness PASS 주장으로 사용하지 않는다. consumer 설치에서는 `.agent-policy/PROJECT.md`를 편집하고 `--project-root <consumer-repo>`로 실제 프로젝트의 경로/Git evidence를 검증한다.

아래 machine-readable block은 validator가 읽는다. 텍스트 설명과 충돌하면 block을 실제 evidence에 맞게 수정한다. object/array/string 타입이 잘못된 malformed block은 readiness 예외로 중단하지 않고 구조화된 `FAIL`로 처리한다.

<!-- project-facts:start -->
```json
{
  "profile": "template",
  "facts": {
    "repository_root": {"value": "", "status": "Unknown", "evidence": ""},
    "primary_source": {"value": "", "status": "Unknown", "evidence": ""},
    "build_command": {"value": "", "status": "Unknown", "evidence": ""},
    "test_command": {"value": "", "status": "Unknown", "evidence": ""},
    "runtime": {"value": "", "status": "Unknown", "evidence": ""},
    "deploy_command": {"value": "", "status": "Unknown", "evidence": ""},
    "deploy_target": {"value": "", "status": "Unknown", "evidence": ""}
  },
  "components": [],
  "review": {
    "reviewed_revision": "",
    "reviewed_at": "",
    "reviewed_paths": []
  }
}
```
<!-- project-facts:end -->

## 작성 규칙

각 fact의 `status`는 다음 중 하나만 사용한다.

- `Confirmed`: 사람이 evidence를 근거로 확인함
- `Inferred`: 정황상 추론했으나 직접 확인되지 않음
- `Unknown`: 아직 모름
- `N/A`: 이 프로젝트에 해당하지 않으며 `evidence`에 이유를 기록함

`Confirmed`는 **문서 상태**다. validator가 source evidence와 연결을 확인했다는 뜻과 동일하지 않으며, command가 실제 실행에 성공했다는 뜻은 더더욱 아니다.

새 저장소에서는 `python scripts/validate.py --bootstrap-project <repo>`로 `PROJECT.inferred.md` 후보를 만들 수 있다. bootstrap은 repository에서 관찰 가능한 source root, task runner, runtime 파일, component 후보를 수집하지만 **어떤 fact도 자동으로 `Confirmed`로 승격하지 않는다**. 생성된 `Inferred` 후보를 evidence와 대조한 뒤 필요한 값만 확인하여 실제 `PROJECT.md`에 반영한다. 기존 후보 파일은 `--bootstrap-force` 없이는 덮어쓰지 않는다.

`review.reviewed_paths`에는 project facts가 실제로 의존하는 manifest, task runner, CI/config, 주요 source root 등을 선택적으로 기록할 수 있다. `reviewed_revision`이 현재 `HEAD`와 달라도 이 경로들이 그 사이 변경되지 않았다면 revision freshness 검증은 통과할 수 있다. 비워 두면 기존처럼 `reviewed_revision == HEAD`를 요구한다.

`evidence`에는 가능한 경우 validator가 확인할 수 있는 형태를 사용한다.

- `path:<relative-or-absolute-path>`: 경로형 fact(`repository_root`, `primary_source`)의 **값과 동일한 경로**인지 확인
- `command-source:<path>::<literal>`: command fact의 literal이 UTF-8 source의 **비주석 active line**에 존재하고 documented command 값과 동일한지 확인한다. `package.json`은 `scripts` 값만 인정한다. 이는 source linkage 검증이지 명령 실행 성공 검증은 아니다.
- `value-source:<path>::<literal>`: runtime/deploy target 같은 값 fact의 literal이 source에 존재하고 documented value와 동일한지 확인
- `contains:<path>::<literal>`: 일반 독립 evidence 확인용. readiness의 typed fact를 자동 `VERIFIED`로 승격하는 용도로는 사용하지 않는다.
- `manual:<description>`: 자동 검증이 부적절하거나 불가능한 근거

예: `path:src`, `command-source:Makefile::python -m unittest`, `value-source:.tool-versions::python 3.12.4`, `manual:runtime confirmed in managed build environment`. `manual:` evidence는 documented readiness에는 사용할 수 있지만 verified readiness는 `PARTIAL`로 남는다.

## Readiness 기준

### Development documented

다음이 `Confirmed` 또는 합리적인 `N/A`여야 한다.

- repository_root
- primary_source
- build_command
- test_command
- runtime
- 최소 한 개 실제 component
- reviewed_revision
- reviewed_at

### Deployment documented

Development 조건에 더해 다음이 `Confirmed` 또는 근거 있는 `N/A`여야 한다.

- deploy_command
- deploy_target

### Evidence-verified / Execution-verified

validator는 자동 확인 가능한 **evidence 연결**만 검증한다. 출력의 `evidence_verified`가 이 범위를 뜻한다. `execution_verified`는 command 자체 실행 성공 여부이며, 이 validator는 명령을 자동 실행하지 않으므로 `NOT_RUN`으로 남는다. 기존 소비자 호환을 위해 `verified` 필드는 `evidence_verified`와 같은 값을 제공한다.


- repository_root와 primary_source가 존재하고 `path:` evidence가 **같은 실제 경로**를 가리키는지
- build/test/deploy command는 `command-source:`의 literal이 source에 존재하며 documented command와 일치하는지
- runtime/deploy target은 `value-source:`의 literal이 source에 존재하며 documented value와 일치하는지
- component path가 존재하는지
- Git 저장소에서는 reviewed_revision이 현재 `HEAD`와 일치하는지
- reviewed_at이 유효한 ISO-8601 date 또는 timezone-aware datetime인지, 미래 시각이 아닌지

command 자체가 안전하게 실행되는지, runtime이 실제 운영 환경과 동일한지처럼 자동 확인이 위험하거나 불가능한 항목은 `MANUAL`이다. `MANUAL`을 `VERIFIED`로 간주하지 않는다. `reviewed_at`이 90일보다 오래되면 readiness를 자동 실패시키지는 않지만 evidence freshness warning을 출력한다.

## 시스템 개요

- 제품/시스템 목적:
- 핵심 사용자 또는 actor:
- 주요 use case:
- 시스템 경계:
- 주요 비기능 요구사항:

## Components / entry points

`components` machine block에는 실제 path가 있는 핵심 component만 넣는다. monorepo나 다중 서비스처럼 component마다 runtime/build/test/deploy가 다르면 선택적 `facts`를 각 component에 둔다. component fact도 root fact와 동일하게 `value/status/evidence`를 사용하며 validator가 선언-evidence 연결을 검증한다.

예:

```json
{
  "name": "api",
  "path": "services/api",
  "responsibility": "HTTP entry points",
  "facts": {
    "runtime": {"value": "Python 3.12", "status": "Confirmed", "evidence": "value-source:services/api/.tool-versions::Python 3.12"},
    "test_command": {"value": "python -m pytest", "status": "Confirmed", "evidence": "command-source:services/api/Makefile::python -m pytest"}
  }
}
```

지원하는 component fact는 `build_command`, `test_command`, `runtime`, `deploy_command`, `deploy_target`이다. 공통 root command가 없으면 root fact를 근거 있는 `N/A`로 두고 component별 사실을 기록할 수 있다.

사람이 읽는 설명에는 필요한 경우 다음을 추가한다.

- entry points / callers / producers
- core processing boundaries
- authoritative state / persistent stores
- events / queues / streams
- generated artifacts
- external systems

## Source of Truth

프로젝트에서 실제 존재하는 위치만 기록한다.

| 종류 | 위치 | 분류 | 비고 |
|---|---|---|---|
| 요구사항 / 제품 의도 |  | Intended |  |
| API / schema / protocol |  | Contract |  |
| 현재 구현 |  | Observed |  |
| 테스트 / 로그 / 측정 |  | Evidence |  |
| 주요 engineering decision |  | Intended / Evidence |  |

빈 전용 디렉터리를 만들기 위해 이 표를 채우지 않는다. 프로젝트가 이미 ADR, specs, plans 체계를 가지고 있으면 그 위치를 가리킨다.

## Data / state

- authoritative state:
- persistent stores:
- cache / derived state:
- transaction / atomicity boundaries:
- retention / lifecycle:

## External boundaries

| 시스템/경계 | 용도 | 인증/권한 | 실패 영향 | contract/evidence |
|---|---|---|---|---|
|  |  |  |  |  |

## Protected invariants / baselines

변경 전후 비교해야 하는 schema/API/file fingerprint, migration state, test baseline 등이 있다면 위치와 확인 방법만 기록한다. 값을 추측하거나 복제하지 않는다.

## Known constraints

-

## Maintenance

entry point, build/test/deploy command, runtime, 주요 component, contract 위치가 바뀌면 이 파일을 갱신하고 `reviewed_revision`과 `reviewed_at`도 함께 갱신한다. 실제 코드/설정과 충돌하면 이 문서를 무조건 믿지 말고 evidence를 다시 확인한다.
