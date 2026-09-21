# Operation extensions and adapter capabilities

Operation extensions add organization/vendor-specific canonical operation IDs without mutating the upstream core catalog. They are **explicit-plan only**: loading an extension never adds natural-language routing aliases.

## Four different guarantees

- **Schema validity** means a document has the expected structure.
- **Integrity** means the exact normalized extension/capability semantics match an expected SHA-256 supplied separately.
- **Capability** means an adapter independently declares that it can observe/enforce a specific operation.
- **Authority / trust** means a higher-authority system decided that the extension/capability declaration is allowed. The reference validator does not authenticate organization identity or establish that authority.

A digest match is therefore not, by itself, organization authorization.

## Extension contract

Extension documents follow `OPERATION_EXTENSION.schema.json` and format `universal-agent-docs-operation-extension-v1`.

Rules that require core context remain cross-document validation rather than JSON Schema alone: namespace collision with core operations, known policy references, deprecation replacement existence, and production Effect not lowering the base floor.

`supported_adapters` is an extension-side allowlist only. It does not prove that an adapter implements the operation.

## Adapter capability contract

Adapter declarations follow `ADAPTER_CAPABILITIES.schema.json` and format `universal-agent-docs-adapter-capabilities-v1`.

For an extension operation to cross the runtime boundary:

1. the operation must exist in a validated extension;
2. the extension must allow the actual adapter ID;
3. the separately loaded capability declaration for that adapter must list the exact operation.

There is no prefix inference or "close enough" operation support.

For `production`, `public`, and `external` environments, the reference validator additionally requires the loaded extension set and capability set to match caller-supplied expected digests. Those expected digests must come from a protected/higher-authority channel. The validator reports integrity matching but still does not authenticate who supplied the expectation.

## CLI example

```bash
python scripts/validate.py \
  --operation-extension examples/extensions/internal-sandbox-artifact.json \
  --adapter-capabilities examples/capabilities/reference-sandbox-artifact-adapter.json \
  --compiled-policy \
  --routing-mode enforcement \
  --operation internal.sandbox_artifact_publish
```

For a production runtime, pin the independently obtained expected digests:

```bash
python scripts/validate.py \
  --operation-extension /protected/policy/internal.json \
  --trusted-extension-digest sha256:... \
  --adapter-capabilities /protected/runtime/adapter-capabilities.json \
  --trusted-capability-digest sha256:... \
  --runtime-action ./runtime-action.json
```

The paths themselves are diagnostic/local metadata. Semantic compiled-policy output binds logical namespaces and canonical digests, not absolute filesystem locations.

## Profile boundaries

Profiles A/B may validate and inspect local extension/capability documents without a trust expectation. That is schema/semantic validation, not authorization. Profile C production enforcement must receive trusted expectations from the integrating higher-authority runtime and must fail closed when the extension or capability integrity is not matched.

The reference implementation still does not provide organization identity authentication, trusted transport, production credential handling, a distributed durable replay ledger, or universal tool interception.
