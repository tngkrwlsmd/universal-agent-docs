# Profile C runtime adapter examples

이 디렉터리는 Profile C의 integration shape를 실행 가능한 로컬 예제로 보여준다. 두 예제 모두 실제 외부 메시지나 production API를 호출하지 않는다.

## Mock message adapter

`mock_runtime.py`는 approval exact binding과 SQLite single-use ledger/replay 차단을 가장 작은 형태로 보여준다.

```bash
python examples/runtime-adapter/mock_runtime.py
```

## Sandbox artifact reference adapter

`sandbox_artifact_adapter.py`는 고정된 adapter surface를 `internal.sandbox_artifact_publish` extension operation으로 독립 매핑하고, Effect/Exposure gate와 extension digest binding을 계산한 뒤 approval을 atomic consume한 경우에만 **실제 로컬 파일 copy**를 수행한다.

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
- validator는 approval object의 schema/time/exact binding/replay를 검증하지만 issuer authority를 인증하지 않는다.
- 예제의 higher-authority/transport boolean은 production identity/transport control을 대신하는 명시적 stand-in이다.
- production에서는 실제 tool/API 호출 앞의 trusted interception, 조직 identity/authorization, shared durable atomic ledger, trusted transport와 final dispatcher enforcement가 별도로 필요하다.
- 이 예제는 특정 vendor/cloud/runtime 전체 지원을 주장하지 않는다.
