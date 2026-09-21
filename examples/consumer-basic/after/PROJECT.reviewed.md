# PROJECT.md — reviewed consumer-basic example

이 파일은 `.agent-policy/PROJECT.md`에 반영할 **reviewed project-facts 예시**다. Policy bundle 자체의 복사본이 아니며, `__REVIEWED_REVISION__`은 실제 소비 저장소에서 `git rev-parse HEAD` 값으로 교체해야 한다.

<!-- project-facts:start -->
```json
{
  "profile": "reviewed-example",
  "facts": {
    "repository_root": {"value": ".", "status": "Confirmed", "evidence": "path:."},
    "primary_source": {"value": "src", "status": "Confirmed", "evidence": "path:src"},
    "build_command": {"value": "python -m compileall src", "status": "Confirmed", "evidence": "command-source:Makefile::python -m compileall src"},
    "test_command": {"value": "python -m unittest discover -s tests -v", "status": "Confirmed", "evidence": "command-source:Makefile::python -m unittest discover -s tests -v"},
    "runtime": {"value": "Python 3.10+", "status": "Confirmed", "evidence": "value-source:pyproject.toml::Python 3.10+"},
    "deploy_command": {"value": "", "status": "N/A", "evidence": "manual:this onboarding example has no deployment flow"},
    "deploy_target": {"value": "", "status": "N/A", "evidence": "manual:this onboarding example has no deployment target"}
  },
  "components": [
    {
      "name": "greeter",
      "path": "src",
      "responsibility": "small Python greeting library"
    }
  ],
  "review": {
    "reviewed_revision": "__REVIEWED_REVISION__",
    "reviewed_at": "2026-09-21T00:00:00+09:00",
    "reviewed_paths": [
      "AGENTS.md",
      "Makefile",
      "pyproject.toml",
      "src",
      "tests"
    ]
  }
}
```
<!-- project-facts:end -->
