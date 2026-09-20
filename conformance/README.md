# Adapter Conformance Kit

이 디렉터리는 runtime/tool adapter가 실제 실행 의미를 `universal-agent-docs`의 canonical operation과 raw exposure facts로 정확히 보고하는지 검증하기 위한 공용 corpus다.

- `golden.json`: 정상 adapter가 반드시 같은 Effect, Exposure, action gate를 만들어야 하는 대표 사례
- `invalid.json`: under-reporting, opaque runtime operation, plan/action mismatch처럼 반드시 fail-closed해야 하는 사례

실행:

```bash
python -m unittest tests.test_conformance -v
```

새 adapter는 이 corpus를 그대로 통과해야 한다. adapter 전용 semantics를 추가할 때는 기존 vector의 의미를 바꾸지 말고 새 vector를 추가한다. 특히 public publish, destructive infrastructure/Git action, credential/tenant scope는 generic command 하나로 축약하지 않는다.
