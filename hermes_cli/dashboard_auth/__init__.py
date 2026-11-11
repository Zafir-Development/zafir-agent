"""Dashboard-auth provider protocol and registry (the browser dashboard itself is gone).

The process-global provider registry and the protocol types remain because bundled
``plugins/dashboard_auth/*`` providers and ``hermes_cli.plugins``/``plugins_context`` import them at
plugin discovery, and a plugin may still register a provider through
``ctx.register_dashboard_auth_provider``. Nothing serves a login page or a browser-authenticated
route after Step 4; the surviving consumer of a provider's session/refresh types is the plugin
contract itself. The fate of those bundled providers is a later-step decision.
"""
from hermes_cli.dashboard_auth.base import (
    DashboardAuthProvider, Session, TokenPrincipal, LoginStart, InvalidCodeError,
    InvalidCredentialsError, ProviderError, RefreshExpiredError, assert_protocol_compliance,
    classify_jwks_lookup_error)
# Dashboard-auth providers are persistent host-owned registrations that deliberately survive a routine
# manager unload (#91701), so the "clean slate" reset must drop the process-global auth registry explicitly
# — otherwise a provider auto-registered during one test leaks into the next.
from hermes_cli.dashboard_auth.registry import (
    register_provider, get_provider, list_providers, list_token_providers,
    list_session_providers, list_interactive_providers, clear_providers)

__all__ = [
    "DashboardAuthProvider",
    "InvalidCodeError",
    "InvalidCredentialsError",
    "LoginStart",
    "ProviderError",
    "RefreshExpiredError",
    "Session",
    "TokenPrincipal",
    "assert_protocol_compliance",
    "classify_jwks_lookup_error",
    "clear_providers",
    "get_provider",
    "list_interactive_providers",
    "list_providers",
    "list_session_providers",
    "list_token_providers",
    "register_provider",
]
