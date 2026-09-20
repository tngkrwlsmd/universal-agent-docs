# Adapter Conformance Kit

이 디렉터리는 runtime/tool adapter가 실제 실행 의미를 `universal-agent-docs`의 canonical operation과 raw exposure facts로 정확히 보고하는지 검증하기 위한 **minimum cross-adapter corpus**다. 전체 operation catalog의 완전한 인증을 의미하지 않으며, 공통 개발·데이터·보안·Git·file I/O·deployment/observability 계열의 대표 위험 경계를 고정한다.

- `golden.json`: 정상 adapter가 반드시 같은 Effect, Exposure, action gate를 만들어야 하는 대표 사례
- `invalid.json`: under-reporting, opaque runtime operation, plan/action mismatch처럼 반드시 fail-closed해야 하는 사례

실행:

```bash
python -m unittest tests.test_conformance -v
```

새 adapter는 이 최소 corpus를 그대로 통과해야 한다. adapter 전용 semantics를 추가할 때는 기존 vector의 의미를 바꾸지 말고 새 vector를 추가한다. `tests/test_conformance.py`는 필수 cross-family operation이 golden corpus에서 빠지지 않는지도 검사한다. 전체 catalog 중 adapter가 실제 지원하는 operation은 별도 adapter-specific vector로 보강해야 하며, corpus PASS를 미지원 operation까지 인증한 것으로 확대 해석하지 않는다. 특히 public publish, destructive infrastructure/Git action, credential/tenant scope는 generic command 하나로 축약하지 않는다.
