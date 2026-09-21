# Practical evaluation corpus

이 디렉터리는 **정책 contract의 정합성을 증명하는 conformance suite가 아니다.** 실제 개발 요청과 프로젝트 유형에서 routing, Effect/Exposure, gate, unknown/fail-closed 동작이 얼마나 잘 맞는지 관찰하는 비규범적 evaluation corpus다.

`conformance/`가 "구현체가 동일한 normative semantics를 구현했는가"를 검증한다면, `evaluation/`은 "현재 semantics와 자연어 routing이 대표적인 실전 작업에서 유용한가"를 측정한다. Evaluation mismatch는 곧 contract 위반을 뜻하지 않으며, alias 품질이나 정책 모델을 개선할 근거다.


> `evaluation/README.md`는 orientation을 위해 consumer bundle에도 포함될 수 있지만, corpus와 runner 자체는 canonical **source artifact/source checkout 전용**이다. 아래 명령은 source repository root에서 실행한다.

```bash
python scripts/evaluate.py
python scripts/evaluate.py --json
python scripts/evaluate.py --fail-on-mismatch
```

현재 corpus는 Python, Node.js/TypeScript, Go, JVM, monorepo, Docker, GitHub Actions, Terraform/IaC, database migration과 multi-operation/unknown/readiness/runtime boundary 사례를 포함한다. 외부 오픈소스 저장소를 vendoring하지 않고 최소 representative scenario를 사용해 결과를 재현 가능하게 유지한다.

주요 지표는 `total_scenarios`, `routing_exact_match`, `routing_acceptable_match`, `false_positive`, `false_negative`, `gate_mismatch`, `unknown_handled_correctly`다. CI hard gate로 사용할지는 별도 결정이며, 기본 runner는 mismatch를 보고만 한다. `--fail-on-mismatch`를 명시해야 종료 코드가 실패한다.
