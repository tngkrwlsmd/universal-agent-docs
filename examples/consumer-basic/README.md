# Profile A/B consumer example

이 디렉터리는 처음 도입하는 작은 Python 프로젝트가 **기존 project instruction을 보존하면서 Profile A를 연결하고, 같은 bundle의 validator를 활성화해 Profile B로 올라가는 흐름**을 보여주는 source example이다.

정책 파일을 여기 복제하지 않는다. 실제 `.agent-policy/`는 canonical consumer artifact에서 설치한다. 이 example은 source repository와 canonical source Release artifact `universal-agent-docs.zip`에는 포함되지만 consumer `.agent-policy` artifact에는 포함되지 않는다.

- `before/`: universal policy를 도입하기 전의 작은 프로젝트
- `after/`: project-owned 파일이 어떤 모양이 되는지 보여주는 예시
- `after/PROJECT.reviewed.md`: bootstrap candidate를 사람이 검토한 뒤 `.agent-policy/PROJECT.md`에 반영할 project-facts 예시

전체 설치와 Profile 의미의 primary owner는 [Adoption profiles](../../docs/adoption-profiles.md)다.

## 1. 기존 프로젝트 확인

```bash
python -c "from pathlib import Path; import shutil; dst=Path('consumer-basic-work'); shutil.rmtree(dst, ignore_errors=True); shutil.copytree(Path('examples/consumer-basic/before'), dst)"
cd consumer-basic-work
python -m unittest discover -s tests -v
cd ..
```

위 준비 명령은 Python 표준 라이브러리와 shell의 `cd`만 사용하므로 Windows PowerShell, macOS, Linux에서 같은 형태로 사용할 수 있다. 예제의 `Makefile`은 project command evidence 예시이며 `make` 설치는 이 walkthrough의 필수 조건이 아니다.

기존 `AGENTS.md`에는 이미 project-specific instruction이 있다. 이후 단계에서도 이 내용을 보존한다.

## 2. Consumer artifact 준비와 staging

Source checkout에서 unreleased `main`을 평가하는 경우 repository root에서 실행한다.

```bash
python -m pip install --require-hashes --requirement requirements.lock
python scripts/package_consumer.py --output-dir dist
python -c "from pathlib import Path; import shutil; p=Path('uad-stage'); shutil.rmtree(p, ignore_errors=True); p.mkdir()"
python -m zipfile -e dist/universal-agent-docs-consumer.zip uad-stage
```

Published production adoption에서는 source-built ZIP 대신 최신 immutable SemVer Release의 consumer artifact를 우선한다.

Staging tree의 `universal-agent-docs-consumer/.agent-policy/`를 소비 프로젝트에 복사한다. 기존 root `AGENTS.md`를 자동 overwrite하지 않는다.

## 3. 기존 AGENTS.md를 보존해 router 병합

`before/AGENTS.md`와 [after/AGENTS.md](after/AGENTS.md)를 비교한다.

After 예시는 기존 두 project instruction을 그대로 유지하고 다음 router만 추가한다.

```markdown
## Universal agent policy

Before making repository changes, read and apply `.agent-policy/AGENTS.md` in addition to the project-specific rules above.
If the two instruction sets appear to conflict, do not silently discard either one; resolve the instruction hierarchy explicitly.
```

이 상태에서 policy instructions를 읽히는 것만 사용한다면 **Profile A**다. Consumer ZIP 설치 자체가 Profile C를 의미하지 않는다.

## 4. PROJECT bootstrap candidate 생성

설치된 bundle을 기준으로 소비 프로젝트에서 실행한다.

```bash
python .agent-policy/scripts/validate.py --bootstrap-project . --bootstrap-output ./PROJECT.candidate.md
```

`PROJECT.candidate.md`는 임시 review artifact다. Canonical project facts 문서는 기본적으로 `.agent-policy/PROJECT.md`이며 candidate 자체가 canonical 문서가 아니다.

Bootstrap이 발견한 facts는 `Inferred` 또는 `Unknown`으로 남는다. 자동 발견만으로 `Confirmed`가 되지 않는다.

## 5. 사람이 facts를 검토

[after/PROJECT.reviewed.md](after/PROJECT.reviewed.md)는 이 예제의 source, Makefile, pyproject를 사람이 확인했다고 가정한 예시다.

실제 소비 저장소에서는:

1. candidate와 source/config를 대조한다.
2. 맞는 fact만 `Confirmed` 또는 근거 있는 `N/A`로 정리한다.
3. `__REVIEWED_REVISION__`을 실제 `git rev-parse HEAD`로 교체한다.
4. 검토 결과를 `.agent-policy/PROJECT.md`에 반영한다.

Project facts를 upstream policy 파일과 별도의 두 번째 policy Source of Truth로 사용하지 않는다. 이 파일은 **소비 프로젝트에 대한 facts**만 소유한다.

## 6. Profile B validation

Validator dependency를 설치한 뒤:

```bash
python -m pip install --require-hashes --requirement .agent-policy/requirements.lock
python .agent-policy/scripts/validate.py --project-root . --readiness development
python .agent-policy/scripts/validate.py --routing-mode enforcement --route "modify the greeter and run tests" --operation code.modify --operation test.execute --resource src/greeter.py
python .agent-policy/scripts/validate.py --compiled-policy --operation code.modify --resource src/greeter.py
```

Bundle/readiness/routing/risk를 자동 검증하기 시작하면 **Profile B**다.

`documented=PASS`나 `evidence_verified=PASS`는 `python -m unittest ...`를 validator가 실제 실행해 성공했다는 뜻이 아니다. Command execution evidence는 별도로 실행하고 보고해야 하며 validator의 기본 `execution_verified`는 `NOT_RUN`이다.

## 7. 여기까지는 Profile C가 아니다

이 example에는 trusted tool/API interception, independently observed actual operation, organization issuer authentication, trusted transport, shared atomic replay ledger, final dispatcher가 없다.

따라서:

```text
consumer ZIP 설치 != Profile C
bootstrap candidate != canonical PROJECT.md
readiness PASS != build/test command 실행 성공
```

Profile C가 필요하면 [Adoption profiles](../../docs/adoption-profiles.md)의 runtime boundary와 [runtime adapter examples](../runtime-adapter/README.md)를 별도로 따른다.
