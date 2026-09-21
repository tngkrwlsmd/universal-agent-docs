# Profile C mock runtime adapter

이 디렉터리는 Profile C의 **integration shape를 실행 가능한 로컬 예제로 보여주기 위한 source-repository example**이다. 실제 외부 메시지나 API를 호출하지 않는다.

실행:

```bash
python -m pip install --require-hashes --requirement requirements.lock
python examples/runtime-adapter/mock_runtime.py
```

예제는 다음 흐름을 수행한다.

```text
planned external.message_send
→ mock adapter가 actual operation/target/exposure facts를 구성
→ Effect/Exposure/gate + action digest 계산
→ exact approval assertion 생성
→ SQLite single-use ledger에서 atomic consume
→ 로컬 mock executor 1회 실행
→ 동일 approval + nonce 재사용
→ REPLAY_DETECTED, 두 번째 실행 차단
```

중요한 경계:

- `validate_approval_assertion`은 schema, 시간, exact action binding과 replay를 검증하지만 issuer authority를 인증하지 않는다.
- 예제의 higher-authority/transport 확인은 production identity/transport control을 대신하는 **명시적 mock**이다.
- production에서는 실제 tool/API 호출을 실행 전에 intercept하는 trusted adapter, 조직 identity/authorization, shared durable atomic ledger, trusted transport와 final dispatcher enforcement가 별도로 필요하다.
- 이 예제는 특정 vendor/cloud/runtime adapter 지원을 주장하지 않는다.
