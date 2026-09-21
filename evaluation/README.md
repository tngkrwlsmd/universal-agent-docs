# Practical evaluation corpus

이 디렉터리는 **정책 contract의 정합성을 증명하는 conformance suite가 아니다.** 실제 개발 요청과 프로젝트 유형에서 routing, Effect/Exposure, gate, unknown/fail-closed 동작이 대표적인 입력에서 어떻게 작동하는지 관찰하는 비규범적 regression evidence다.

`conformance/`가 "구현체가 동일한 normative semantics를 구현했는가"를 검증한다면, `evaluation/`은 "현재 semantics와 자연어 routing이 대표적인 실전 작업에서 유용한가"를 측정한다. PASS는 전체 자연어 정확도나 production safety를 증명하지 않는다.

- `smoke.json`: 프로젝트 유형과 핵심 경계를 빠르게 확인하는 기본 사례
- `regression.json`: 과거에 취약하기 쉬운 paraphrase, 한국어/혼합어, typo, negation, read-only/write ambiguity, multi-intent, untrusted instruction-looking data, unknown 사례
- `scenarios.json`: 이전 source 사용자와의 호환성을 위해 유지되는 legacy smoke corpus

Source repository root에서:

```bash
python scripts/evaluate.py
python scripts/evaluate.py --json
python scripts/evaluate.py --fail-on-mismatch
python scripts/evaluate.py --corpus evaluation/regression.json --fail-on-mismatch
```

기본 실행은 smoke + regression을 합쳐 scenario ID 중복을 거부한다. 주요 지표는 `routing_exact_match`, `routing_expected_covered`, `unexpected_operation_count`, `false_positive`, `false_negative`, `effect_mismatch`, `exposure_mismatch`, `gate_mismatch`, `readiness_mismatch`, `unknown_handled_correctly`다. `routing_expected_covered`는 expected operation이 모두 포함되었는지만 뜻하며, unexpected operation은 별도 지표로 반드시 확인한다.

Corpus와 alias가 같은 공개 저장소에서 함께 진화하므로 이것을 비공개 holdout으로 취급하지 않는다. 새로 발견된 false-positive/false-negative/ambiguity는 regression corpus에 고정하고, conformance PASS와 evaluation quality를 같은 의미로 해석하지 않는다.
