# Active Plugin Registry

The active-plugin registry is a read projection over the durable plugin store. It
lists plugins currently in `enabled` state and groups the extension-point kinds they
inhabit.

Query it through the Control Plane:

```http
GET /v2/plugins/active
```

Response payloads always carry `schemaVersion`:

```json
{
  "schemaVersion": "1",
  "activePlugins": [
    {
      "id": "acme/example-plugin",
      "version": "0.1.0",
      "state": "enabled",
      "extensionPoints": [
        {
          "kind": "skill",
          "id": "acme/example-plugin.skill",
          "contract": "^1.0"
        }
      ]
    }
  ],
  "inhabitedExtensionPoints": [
    {
      "kind": "skill",
      "pluginIds": ["acme/example-plugin"]
    }
  ]
}
```

The projection is consistent with lifecycle transitions: `enable` adds a plugin to
the active set, while `disable` removes it. Development hot reload validates and
registers the changed plugin before mutating durable state; failed reloads keep the
previous enabled version active and emit `plugin.reload.failed`.
