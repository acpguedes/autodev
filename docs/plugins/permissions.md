# Plugin Permissions

E1 enforces least privilege for plugin execution. Missing manifest permissions grant
nothing: filesystem, network, command execution, and secrets are all denied by default.

Permissions are declared in `plugin.yaml`:

```yaml
permissions:
  filesystem:
    read:
      - "${workspace}/src"
    write:
      - "${workspace}/.autodev/cache"
  network:
    egress:
      - "api.example.com:443"
  exec:
    commands:
      - "pytest"
  secrets:
    - name: TOKEN
      required: true
```

The Plugin Host passes plugin code a scoped Host API. Plugin code must use that API
for mediated access:

- `host.read_text(path)` and `host.write_text(path, content)` enforce declared paths.
- `host.open_network(hostname, port)` enforces declared `host:port` egress.
- `host.run_command(command)` enforces declared command names.
- `host.get_secret(name)` only returns declared secrets supplied by the host.

The import sandbox also blocks direct imports of network, exec, and secret helper
modules when the corresponding permission block is absent. A blocked operation raises
`PermissionDenied`, stores the plugin as `quarantined` when it happens during enable,
and emits:

| Event | Payload |
| --- | --- |
| `plugin.permission.denied` | `capability`, `detail` |

Do not add implicit grants in tests or production fixtures. If a plugin needs access,
declare it in the fixture or manifest and let the broker enforce the boundary.
