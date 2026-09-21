# Profile C runtime adapter examples

이 디렉터리는 Profile C의 integration shape를 실행 가능한 로컬 예제로 보여준다. 두 예제 모두 실제 외부 메시지나 production API를 호출하지 않는다.

## Mock message adapter

`mock_runtime.py`는 approval exact binding과 SQLite single-use ledger/replay 차단을 가장 작은 형태로 보여준다.

```bash
python examples/runtime-adapter/mock_runtime.py
```

## Sandbox artifact reference adapter

`sandbox_artifact_adapter.py`는 고정된 adapter surface를 `internal.sandbox_artifact_publish` extension operation으로 독립 매핑한다. Extension allowlist와 `examples/capabilities/reference-sandbox-artifact-adapter.json`의 adapter capability 선언을 모두 확인하고, Effect/Exposure gate와 extension/capability digest binding을 계산한 뒤 approval을 atomic consume한 경우에만 **실제 로컬 파일 copy**를 수행한다.

```bash
python examples/runtime-adapter/sandbox_artifact_adapter.py
```

흐름:

```text
explicit plan
→ adapter가 actual operation/target/exposure facts를 독립 구성
→ extension namespace + adapter capability 확인
→ Effect/Exposure/gate + action digest 계산
→ exact approval assertion 검증
→ SQLite single-use ledger atomic consume
→ sandbox filesystem write
→ audit result
→ 동일 approval + nonce replay 차단
```

중요한 경계:

- 예제의 파일 write는 임시/local sandbox 안에서만 수행되며 실제 artifact registry publish가 아니다.
- extension/capability schema validity와 digest integrity는 조직 authority를 인증하지 않는다. production/public/external에서는 separately supplied expected digests가 필요하고, 그 expectation을 누가 권한 있게 제공했는지는 higher-authority runtime 책임이다.
- validator는 approval object의 schema/time/exact binding/replay를 검증하지만 issuer authority를 인증하지 않는다.
- 예제의 higher-authority/transport boolean은 production identity/transport control을 대신하는 명시적 stand-in이다.
- production에서는 실제 tool/API 호출 앞의 trusted interception, 조직 identity/authorization, shared durable atomic ledger, trusted transport와 final dispatcher enforcement가 별도로 필요하다.
- 이 예제는 특정 vendor/cloud/runtime 전체 지원을 주장하지 않는다.

## GitHub issue production-shaped reference adapter

`github_issue_adapter.py`는 core canonical operation `external.api_write`를 GitHub issue-create surface에 고정해 **실제 production integration에서 필요한 경계 순서**를 보여준다. 테스트와 demo는 `RecordingGitHubTransport`만 사용하며 네트워크나 실제 GitHub side effect를 발생시키지 않는다.

```bash
python examples/runtime-adapter/github_issue_adapter.py
```

핵심 차이는 precomputed boundary를 dispatcher가 그대로 믿지 않는다는 점이다. Dispatcher는 실제로 전송하려는 repository/title/body에서 target과 semantic digest를 다시 구성하고, 그 시점의 boundary를 다시 계산한 뒤 exact approval을 atomic consume한다. 따라서 승인 뒤 repository target이나 issue content가 바뀌면 transport 호출 전에 차단된다.

이 reference가 보여주는 보장:

- fixed tool surface에서 actual operation을 adapter가 독립 구성
- concrete GitHub repository target과 external environment를 실행 직전에 재관찰
- title/body digest를 `semantic_details`로 action digest에 결박
- plan/actual mismatch, unknown/opaque operation, exposure fact 누락 fail-closed
- approval exact binding, TTL과 single-use replay consume 후에만 dispatcher 호출

이 reference가 **보장하지 않는 것**:

- 실제 GitHub credential identity/authz
- HTTPS endpoint/transport authenticity 자체의 구현
- 모든 GitHub API surface의 interception
- 분산 production shared replay ledger
- GitHub API 성공과 audit sink를 하나의 exactly-once transaction으로 만드는 것

Production에서는 위 항목을 소비 환경이 제공해야 한다. 전체 공격 모델과 residual risk는 [`docs/threat-model.md`](../../docs/threat-model.md)를 따른다.
