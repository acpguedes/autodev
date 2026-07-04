# Write Your First Plugin

Create a plugin scaffold from the repository root:

```bash
source .venv/bin/activate
python -m backend.sdk.cli new plugin acme/hello-plugin --output /tmp/hello-plugin
```

The same command is available through the main CLI:

```bash
source .venv/bin/activate
python -m backend.cli sdk new plugin acme/hello-plugin --output /tmp/hello-plugin
```

The scaffold writes:

- `plugin.yaml` with `schemaVersion`, `id`, SemVer `version`, `hostApi`, runtime, and
  extension point declarations.
- `<plugin_module>.py` with a typed `register(host: HostApi)` entrypoint.
- `tests/test_contract.py` using the contract-test harness.
- `pyproject.toml` and `README.md`.

Run the generated contract test:

```bash
cd /tmp/hello-plugin
PYTHONPATH=/path/to/autodev python -m pytest tests -q
```

Contract tests validate the manifest, install the plugin in an ephemeral durable store,
and enable it through the real Plugin Host. A plugin that fails manifest validation,
`hostApi` compatibility, declared extension registration, or permission enforcement
returns a failing `ContractTestResult` with actionable errors.

Python contracts live in `backend.sdk.contracts` and are versioned by
`SDK_CONTRACT_VERSION`. The minimal TypeScript UI-panel contract stub is published at
`sdk/typescript/contracts.ts`.

A runnable example is available in `examples/plugins/hello-plugin`.
