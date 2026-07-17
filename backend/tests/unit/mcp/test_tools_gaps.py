"""Unit tests filling coverage gaps in ``backend/mcp/tools.py``.

Complements ``backend/tests/test_mcp_tools.py`` (not modified here), which
already exercises allowlist enforcement and successful tool discovery/calls
through a reference subprocess server. This file targets the branches that
file does not reach: ``McpServerConfig.__post_init__`` validation errors,
``McpServerConfig.from_mapping()`` edge cases, ``McpToolProvider._connect_one``'s
``McpError`` discovery-failure branch, ``_build_client``'s HTTP-transport
branch, and ``McpToolProvider.close()`` idempotency.

No live network or subprocess I/O beyond a small reference stdio script is
used; the HTTP-transport branch is exercised at construction time only, so no
real HTTP request is ever made.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from backend.mcp.client import McpHttpClient, McpStdioClient
from backend.mcp.tools import McpServerConfig, McpToolProvider, _build_client


# ---------------------------------------------------------------------------
# McpServerConfig.__post_init__ — validation errors
# ---------------------------------------------------------------------------


def test_config_rejects_unsupported_transport() -> None:
    """Constructing a config with an unknown transport raises ``ValueError``."""
    with pytest.raises(ValueError, match="unsupported transport"):
        McpServerConfig(name="broken", transport="carrier-pigeon")  # type: ignore[arg-type]


def test_config_rejects_stdio_without_command() -> None:
    """A ``stdio`` transport with an empty ``command`` raises ``ValueError``."""
    with pytest.raises(ValueError, match="requires a non-empty command"):
        McpServerConfig(name="broken", transport="stdio", command=())


def test_config_rejects_http_without_url() -> None:
    """An ``http`` transport with an empty ``url`` raises ``ValueError``."""
    with pytest.raises(ValueError, match="requires a url"):
        McpServerConfig(name="broken", transport="http", url="")


def test_config_accepts_valid_stdio_config() -> None:
    """A well-formed ``stdio`` config constructs without raising."""
    config = McpServerConfig(name="ok", transport="stdio", command=("echo",))

    assert config.command == ("echo",)


# ---------------------------------------------------------------------------
# McpServerConfig.from_mapping() — edge cases
# ---------------------------------------------------------------------------


def test_from_mapping_rejects_missing_name() -> None:
    """A mapping without a non-empty ``name`` raises ``ValueError``."""
    with pytest.raises(ValueError, match="non-empty 'name'"):
        McpServerConfig.from_mapping({"transport": "stdio", "command": ["echo"]})


def test_from_mapping_rejects_empty_name() -> None:
    """A mapping with an empty-string ``name`` raises ``ValueError``."""
    with pytest.raises(ValueError, match="non-empty 'name'"):
        McpServerConfig.from_mapping({"name": "", "transport": "stdio", "command": ["echo"]})


def test_from_mapping_rejects_invalid_transport() -> None:
    """A mapping with an unrecognized ``transport`` raises ``ValueError``."""
    with pytest.raises(ValueError, match="'transport' must be one of"):
        McpServerConfig.from_mapping({"name": "svc", "transport": "carrier-pigeon"})


def test_from_mapping_rejects_missing_transport() -> None:
    """A mapping without a ``transport`` key raises ``ValueError``."""
    with pytest.raises(ValueError, match="'transport' must be one of"):
        McpServerConfig.from_mapping({"name": "svc"})


def test_from_mapping_applies_defaults_for_optional_fields() -> None:
    """Omitted ``url``/``allowlist``/``timeoutS`` fall back to their defaults."""
    config = McpServerConfig.from_mapping({"name": "svc", "transport": "stdio", "command": ["echo"]})

    assert config.url == ""
    assert config.allowlist == ()
    assert config.timeout_s == 10.0


def test_from_mapping_coerces_non_sequence_command_and_allowlist_to_empty() -> None:
    """A non-list/tuple ``command``/``allowlist`` value is silently coerced to ``()``."""
    config = McpServerConfig.from_mapping(
        {
            "name": "svc",
            "transport": "http",
            "url": "http://example.invalid/mcp",
            "command": "not-a-sequence",
            "allowlist": "also-not-a-sequence",
        }
    )

    assert config.command == ()
    assert config.allowlist == ()


def test_from_mapping_reads_full_payload() -> None:
    """A fully-populated mapping is translated field-for-field."""
    config = McpServerConfig.from_mapping(
        {
            "name": "svc",
            "transport": "stdio",
            "command": ["python", "-m", "server"],
            "allowlist": ["tool_a", "tool_b"],
            "timeoutS": 5.5,
        }
    )

    assert config.name == "svc"
    assert config.command == ("python", "-m", "server")
    assert config.allowlist == ("tool_a", "tool_b")
    assert config.timeout_s == 5.5


# ---------------------------------------------------------------------------
# _build_client — HTTP-transport branch
# ---------------------------------------------------------------------------


def test_build_client_selects_stdio_client() -> None:
    """``_build_client`` returns an :class:`McpStdioClient` for ``transport="stdio"``."""
    config = McpServerConfig(name="svc", transport="stdio", command=("echo",))

    client = _build_client(config)

    assert isinstance(client, McpStdioClient)


def test_build_client_selects_http_client_without_network_access() -> None:
    """``_build_client`` returns an :class:`McpHttpClient` for ``transport="http"``.

    Construction alone performs no network I/O — only ``initialize()``/
    ``call_tool()`` would, and neither is invoked here.
    """
    config = McpServerConfig(name="svc", transport="http", url="http://example.invalid/mcp")

    client = _build_client(config)

    assert isinstance(client, McpHttpClient)


# ---------------------------------------------------------------------------
# McpToolProvider._connect_one — McpError discovery-failure branch
# ---------------------------------------------------------------------------

_FAILING_SERVER_SOURCE = textwrap.dedent(
    """
    import sys

    # Exit immediately without responding to any request. The client's first
    # read against the closed stdout observes EOF, which McpStdioClient
    # surfaces as an McpError from within initialize().
    sys.exit(0)
    """
)


@pytest.fixture
def failing_server_script(tmp_path: Path) -> Path:
    """Write a reference stdio script that exits before answering any request."""
    script = tmp_path / "failing_mcp_server.py"
    script.write_text(_FAILING_SERVER_SOURCE)
    return script


def test_connect_one_skips_server_on_discovery_failure(failing_server_script: Path) -> None:
    """A server whose ``initialize()`` fails is skipped, not registered, and closed."""
    config = McpServerConfig(
        name="flaky",
        transport="stdio",
        command=(sys.executable, str(failing_server_script)),
        allowlist=("some_tool",),
    )
    provider = McpToolProvider([config])

    tools = provider.connect()

    assert tools == {}
    assert provider.tools == {}
    provider.close()


def test_connect_skips_server_with_empty_allowlist() -> None:
    """A server config with no allowlist entries is skipped without connecting."""
    config = McpServerConfig(name="unused", transport="stdio", command=("echo",), allowlist=())
    provider = McpToolProvider([config])

    tools = provider.connect()

    assert tools == {}
    provider.close()


# ---------------------------------------------------------------------------
# McpToolProvider.close() — idempotency
# ---------------------------------------------------------------------------


def test_close_is_idempotent_when_never_connected() -> None:
    """Calling ``close()`` on a never-connected provider does not raise."""
    provider = McpToolProvider([])

    provider.close()
    provider.close()


def test_close_is_idempotent_after_a_failed_connect(failing_server_script: Path) -> None:
    """Calling ``close()`` twice after a discovery failure does not raise."""
    config = McpServerConfig(
        name="flaky",
        transport="stdio",
        command=(sys.executable, str(failing_server_script)),
        allowlist=("some_tool",),
    )
    provider = McpToolProvider([config])
    provider.connect()

    provider.close()
    provider.close()


def test_context_manager_connects_and_closes() -> None:
    """``McpToolProvider`` used as a context manager connects on enter, closes on exit."""
    with McpToolProvider([]) as provider:
        assert provider.tools == {}
