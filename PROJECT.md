# PROJECT.md — universal-agent-docs project facts

이 파일은 **이 upstream 저장소 자체**의 현재 project facts와 architecture/readiness를 기록한다. 다른 프로젝트에 설치할 때 사용하는 빈 양식은 [`PROJECT.template.md`](PROJECT.template.md)이며, consumer bundle에서는 그 template이 `.agent-policy/PROJECT.md`로 vendoring된다.

<!-- project-facts:start -->
```json
{
  "profile": "source",
  "facts": {
    "repository_root": {"value": ".", "status": "Confirmed", "evidence": "path:."},
    "primary_source": {"value": "scripts", "status": "Confirmed", "evidence": "path:scripts"},
    "build_command": {"value": "python scripts/package.py --output-dir dist", "status": "Confirmed", "evidence": "command-source:.github/workflows/ci.yml::python scripts/package.py --output-dir dist"},
    "test_command": {"value": "python -m unittest discover -s tests -v", "status": "Confirmed", "evidence": "command-source:.github/workflows/ci.yml::python -m unittest discover -s tests -v"},
    "runtime": {"value": "Python 3.10+", "status": "Confirmed", "evidence": "value-source:README.md::Python 3.10+"},
    "deploy_command": {"value": "", "status": "N/A", "evidence": "manual:this repository publishes release artifacts but has no application deployment command"},
    "deploy_target": {"value": "", "status": "N/A", "evidence": "manual:no application deployment target"}
  },
  "components": [
    {"name": "policy", "path": "POLICIES.md", "responsibility": "human-facing policy semantics"},
    {"name": "machine-contract", "path": "POLICY_CONTRACT.json", "responsibility": "machine-enforceable policy semantics"},
    {"name": "validator-packagers", "path": "scripts", "responsibility": "validation and source/consumer packaging"},
    {"name": "conformance", "path": "conformance", "responsibility": "cross-adapter conformance corpus"},
    {"name": "tests", "path": "tests", "responsibility": "regression, fuzz, packaging and conformance tests"}
  ],
  "review": {
    "reviewed_revision": "3e5ed1ec1e5251d80e670b7484a861ce591a8321",
    "reviewed_at": "2026-09-20",
    "reviewed_paths": [
      ".github/workflows/ci.yml",
      "scripts/validate.py",
      "scripts/package.py",
      "scripts/package_consumer.py",
      "README.md",
      "POLICY_CONTRACT.json"
    ]
  }
}
```
<!-- project-facts:end -->

## 시스템 개요

- 목적: 특정 언어·프레임워크·클라우드·에이전트 vendor에 종속되지 않는 개발 에이전트 정책과 reference enforcement contract를 제공한다.
- 핵심 사용자/actor: 개발 에이전트 runtime, tool adapter 구현자, 정책을 소비 프로젝트에 설치하는 개발자/조직.
- 핵심 경계: human policy, machine policy contract, runtime action assertion, approval/override binding, packaging/release provenance.
- 배포물: source distribution과 collision-safe consumer distribution을 별도로 생성한다.

## Source of Truth

| 종류 | 위치 | 분류 | 비고 |
|---|---|---|---|
| root instruction/router | `AGENTS.md` | Contract | 모든 작업의 최소 불변조건과 policy routing |
| human policy semantics | `POLICIES.md` | Contract / Intended | 사람용 절차·근거의 primary owner |
| machine enforcement semantics | `POLICY_CONTRACT.json` + schemas | Contract | canonical operation, risk gate, distribution/integrity contract |
| routing fallback | `ROUTING_ALIASES.json` | Contract | 자연어 advisory mapping |
| runtime/approval wire format | `RUNTIME_ACTION.schema.json`, `APPROVAL_ASSERTION.schema.json`, `PROTECTED_OVERRIDE.schema.json` | Contract | runtime boundary objects |
| validator/packager | `scripts/` | Observed | reference implementation |
| conformance corpus | `conformance/` | Evidence / Contract | minimum cross-adapter behavior |
| regression tests | `tests/` | Evidence | validator, archive, package, policy regression |
| CI/release | `.github/workflows/` | Evidence / Contract | cross-platform qualification and provenance |

## Build / test / release flow

```text
bundle validation
  → unit/fuzz/conformance tests
  → source + consumer package
  → source/consumer distribution verification
  → cross-platform artifact SHA equality
  → protected-main release workflow
  → artifact attestation
  → independent release verification
```

CI qualification은 Linux/macOS/Windows에서 Python 3.10과 3.14를 사용하며, 기존 required check 이름을 유지한 `ubuntu-latest / Python 3.14` job이 전체 matrix의 artifact reproducibility를 집계한다.

## Data / state

이 저장소는 application database나 customer state를 소유하지 않는다. 지속 상태는 Git repository history, GitHub repository rules, CI/release artifacts와 attestation이다. approval/override SQLite ledger는 reference validator 기능이며 저장소의 canonical persistent state가 아니다.

## External boundaries

| 시스템/경계 | 용도 | 인증/권한 | 실패 영향 | contract/evidence |
|---|---|---|---|---|
| GitHub repository | protected main, PR integration | GitHub repository permissions/ruleset | canonical source integrity | active `Protect main` ruleset |
| GitHub Actions | CI/release | workflow token permissions | qualification/provenance | `.github/workflows/*.yml` |
| GitHub Artifact Attestation | release provenance | OIDC/Sigstore | publisher/source provenance | release + verify workflows |
| PyPI dependency resolution | validator dependency installation | public registry + hash lock | validator environment | `requirements.lock` |

## Protected invariants / baselines

- `main`은 repository Ruleset의 PR/required-check/linear-history/force-push/delete 규칙을 통과해야 한다.
- source 및 consumer ZIP은 지원 CI matrix에서 bit-for-bit 동일해야 한다.
- source distribution과 consumer distribution은 각각 exact file set과 detached integrity metadata에 결박된다.
- machine policy semantic change는 schema version lifecycle 규칙을 따른다.
- approval/override binding은 action digest와 single-use nonce를 사용한다.

## Known constraints

- validator는 모든 human prose 문장을 의미론적으로 해석하지 않는다. 자동 parity는 explicit machine-readable/schema/implementation invariant와 regression test 범위다.
- consumer project facts는 upstream `PROJECT.md`가 아니라 소비 repository가 소유한다.
- GitHub repository-level ruleset 자체는 repository file로 재현되지 않으므로 release provenance와 별도의 governance control이다.

## Maintenance

build/test command, supported runtime, policy schema, distribution layout, workflow path 또는 주요 component가 바뀌면 이 파일의 machine block과 evidence를 갱신한다. `reviewed_revision`은 facts가 검토된 revision을 기록하고 `reviewed_paths`로 무관한 후속 commit과 관련 변경을 구분한다.
