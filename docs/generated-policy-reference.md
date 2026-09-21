# Generated policy reference

> 이 문서는 `POLICY_CONTRACT.json`에서 자동 생성된 deterministic projection이다. Source of Truth가 아니며 직접 수정하지 말고 `python scripts/generate_policy_reference.py`로 갱신한다.

**Effect levels (machine-owned)**

| Level | Meaning |
|---|---|
| L1 | Read-only |
| L2 | Reversible local change |
| L3 | Bounded external side effect |
| L4 | Production, security, public distribution, or effectively irreversible |

**Exposure levels (machine-owned)**

| Level | Meaning |
|---|---|
| X0 | Ordinary / Local / Public |
| X1 | Internal / Limited-sensitive |
| X2 | Restricted / Production / Credential-bearing |
| X3 | Critical / Privileged / Regulated / Broad-scale |

**Effect × Exposure minimum gate**

| Effect \ Exposure | X0 | X1 | X2 | X3 |
|---|---|---|---|---|
| L1 | AUTO | AUTO | AUTO_WITH_GUARDS | REQUIRE_EXPLICIT_APPROVAL |
| L2 | AUTO | AUTO_WITH_GUARDS | REQUIRE_EXPLICIT_APPROVAL | PROHIBITED_WITHOUT_OVERRIDE |
| L3 | REQUIRE_EXPLICIT_APPROVAL | REQUIRE_EXPLICIT_APPROVAL | REQUIRE_EXPLICIT_APPROVAL | PROHIBITED_WITHOUT_OVERRIDE |
| L4 | REQUIRE_EXPLICIT_APPROVAL | REQUIRE_EXPLICIT_APPROVAL | REQUIRE_EXPLICIT_APPROVAL | PROHIBITED_WITHOUT_OVERRIDE |

**Environment Exposure floors**

| Environment | Minimum Exposure |
|---|---|
| local | X0 |
| test | X0 |
| staging | X1 |
| production | X2 |
| public | X0 |
| external | X0 |
| unknown | X2 |

**Execution boundary required inputs**

- `planned_operations`
- `actual_operations`
- `affected_resources`
- `targets`
- `environment`
- `exposure_facts`
- `correlation_id`
- `execution_nonce`

**Raw Exposure fact floors**

| Fact | Value | Minimum Exposure |
|---|---|---|
| `data_classification` | `public` | X0 |
| `data_classification` | `internal` | X1 |
| `data_classification` | `confidential` | X2 |
| `data_classification` | `restricted` | X2 |
| `data_classification` | `regulated` | X3 |
| `data_classification` | `unknown` | X2 |
| `credential_class` | `none` | X0 |
| `credential_class` | `user_secret` | X1 |
| `credential_class` | `service_credential` | X2 |
| `credential_class` | `privileged_credential` | X3 |
| `credential_class` | `break_glass` | X3 |
| `credential_class` | `unknown` | X2 |
| `tenant_scope` | `single_user` | X0 |
| `tenant_scope` | `single_tenant` | X1 |
| `tenant_scope` | `multi_tenant` | X2 |
| `tenant_scope` | `organization_wide` | X3 |
| `tenant_scope` | `global` | X3 |
| `tenant_scope` | `unknown` | X2 |
| `public_visibility` | `none` | X0 |
| `public_visibility` | `public_source` | X0 |
| `public_visibility` | `public_destination` | X2 |
| `public_visibility` | `bidirectional` | X2 |
| `public_visibility` | `unknown` | X2 |
| `estimated_blast_radius` | `single_resource` | X0 |
| `estimated_blast_radius` | `bounded_set` | X1 |
| `estimated_blast_radius` | `service` | X2 |
| `estimated_blast_radius` | `organization` | X3 |
| `estimated_blast_radius` | `global` | X3 |
| `estimated_blast_radius` | `unknown` | X2 |
| `estimated_financial_impact` | `none` | X0 |
| `estimated_financial_impact` | `negligible` | X0 |
| `estimated_financial_impact` | `bounded` | X1 |
| `estimated_financial_impact` | `material` | X2 |
| `estimated_financial_impact` | `critical` | X3 |
| `estimated_financial_impact` | `unknown` | X2 |

**Context Effect escalation rules**

- `public_distribution_publish`: `artifact.publish`, `package.publish` -> `L4` when environment: `public`; exposure_facts.public_visibility: `public_destination`, `bidirectional`

**Operation semantic requirements**

- `tracked_delete_recoverability`: operations `filesystem.tracked_delete`; required details `recoverability`, `recovery_revision`; allowed environments `local`, `test`

**Canonical operation catalog**

| Operation | Policies | Effect floor | Execution policy | Lifecycle |
|---|---|---|---|---|
| `archive.inspect` | file_handling, security | L1 | yes | active |
| `artifact.publish` | deployment, execution | L3 | yes | active |
| `auth.change` | security, implementation, testing | L2 | no | active |
| `build.execute` | implementation, testing, execution | L2 | yes | active |
| `cloud.resource_change` | deployment, execution | L3 | yes | active |
| `cloud.resource_delete` | deployment, execution | L4 | yes | active |
| `code.generate` | dependencies, implementation | L2 | no | active |
| `code.modify` | implementation, testing | L2 | no | active |
| `code.refactor` | implementation, testing | L2 | no | active |
| `command.execute` | execution | L1 | yes | active |
| `credential.rotate` | security, execution | L4 | yes | active |
| `credential.use` | security, execution | L1 | yes | active |
| `data.export` | data_safety, file_handling, execution | L2 | yes | active |
| `database.destructive_change` | data_safety, execution | L4 | yes | active |
| `database.read` | data_safety | L1 | yes | active |
| `database.schema_change` | data_safety, execution | L3 | yes | active |
| `database.write` | data_safety, execution | L3 | yes | active |
| `dependency.change` | dependencies, implementation | L2 | no | active |
| `dependency.install` | dependencies, execution, security | L2 | yes | active |
| `deploy.execute` | deployment, execution | L3 | yes | active |
| `documentation.modify` | implementation | L2 | no | active |
| `external.api_write` | execution | L3 | yes | active |
| `external.message_send` | execution | L3 | yes | active |
| `external.upload` | security, file_handling, execution | L3 | yes | active |
| `file.export` | file_handling | L2 | yes | active |
| `file.import` | file_handling, data_safety | L2 | yes | active |
| `file.parse` | file_handling | L1 | no | active |
| `filesystem.delete` | execution, file_handling | L4 | yes | active |
| `filesystem.generated_delete` | execution, file_handling | L2 | yes | active |
| `filesystem.permission_change` | security, file_handling, execution | L2 | yes | active |
| `filesystem.tracked_delete` | implementation, git, file_handling, execution | L2 | yes | active |
| `format.execute` | implementation, testing, execution | L2 | yes | active |
| `git.branch_change` | git | L2 | yes | active |
| `git.commit` | git | L2 | yes | active |
| `git.destructive_change` | git, execution | L4 | yes | active |
| `git.merge` | git, testing | L2 | yes | active |
| `git.push` | git, execution | L3 | yes | active |
| `git.rebase` | git, testing | L2 | yes | active |
| `iam.change` | security, execution | L4 | yes | active |
| `incident.diagnose` | observability, testing | L1 | yes | active |
| `lint.execute` | implementation, testing, execution | L1 | yes | active |
| `network.configuration_change` | security, deployment, execution | L3 | yes | active |
| `observability.inspect` | observability | L1 | yes | active |
| `package.publish` | dependencies, deployment, execution | L3 | yes | active |
| `performance.diagnose` | observability, testing | L1 | yes | active |
| `permission.change` | security, execution | L3 | yes | active |
| `process.control` | execution | L2 | yes | active |
| `prompt_injection.inspect` | security | L1 | no | active |
| `release.publish` | deployment, execution | L4 | yes | active |
| `rollback.execute` | deployment, testing, execution | L3 | yes | active |
| `secret.read` | security, execution | L1 | yes | active |
| `security.configuration_change` | security, implementation, testing | L2 | no | active |
| `service.restart` | execution, deployment | L3 | yes | active |
| `storage.object_delete` | file_handling, data_safety, execution | L4 | yes | active |
| `test.design` | testing | L2 | no | active |
| `test.execute` | testing, execution | L1 | yes | active |
| `test.scenario.concurrency` | testing, implementation, data_safety, execution | L2 | yes | active |
| `test.scenario.external_system` | testing, execution | L1 | yes | active |
| `test.scenario.file` | testing, file_handling, security, execution | L2 | yes | active |
| `test.scenario.replay_idempotency` | testing, implementation, data_safety, execution | L2 | yes | active |
| `test.scenario.security` | testing, security, execution | L2 | yes | active |
| `test.scenario.toctou` | testing, implementation, execution | L2 | yes | active |
| `test.scenario.transaction_rollback` | testing, data_safety, execution | L2 | yes | active |
| `typecheck.execute` | implementation, testing, execution | L1 | yes | active |

**Approval / override binding**

- approval gate: `REQUIRE_EXPLICIT_APPROVAL`
- approval schema: `APPROVAL_ASSERTION.schema.json`
- approval max TTL: `1800` seconds
- protected override gate: `PROHIBITED_WITHOUT_OVERRIDE`
- protected override schema: `PROTECTED_OVERRIDE.schema.json`
- protected override max TTL: `900` seconds
- action digest format: `universal-agent-docs-action-digest-v3`
