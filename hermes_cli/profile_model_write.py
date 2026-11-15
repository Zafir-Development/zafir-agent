"""Writing a model assignment into a profile's config.yaml — the one validated ``/model`` shape.

The TUI's profile RPCs and the CLI's Local Models flow both change which model a profile runs.
Both go through one place so a pick is normalized, validated against the provider catalog and
credentials, and persisted exactly like ``/model <model> --provider <provider> --global`` —
including for a profile other than the process's own, whose home and secret scope must be
bound around the read and the write.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any, Optional, TYPE_CHECKING

from hermes_cli.profile_scope import CONFIG_MUTATION_LOCK, config_profile_scope, scope_profile_name

if TYPE_CHECKING:
    from hermes_cli.model_switch import ModelSwitchResult

_log = logging.getLogger(__name__)


class MainModelRejected(RuntimeError):
    """A main-slot pick refused by validation. ``detail`` is the user-facing reason."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def _normalize_main_model_assignment(provider: str, model: str) -> tuple[str, str]:
    """Normalize a main-slot (provider, model) pair before persisting.

    The per-card "Use as → Main model" menu can send the model's VENDOR prefix as the
    provider (analytics rows with no ``billing_provider``), producing e.g.
    ``provider: anthropic`` + ``default: anthropic/claude-opus-4.6`` — an aggregator slug on
    the native provider, which 400s. Two repairs at this single chokepoint:

    1. Vendor-name → Hermes-provider: when the provider is not a known provider/alias but the
       model is a vendor-prefixed slug, keep the user's CURRENT aggregator if on one, else
       openrouter. User-declared ``providers:``/``custom_providers:`` entries resolve first,
       and durable named-custom slugs (``custom`` / ``custom:<name>``) are excluded —
       ``_KNOWN_PROVIDER_NAMES`` lists only the bare ``custom`` bucket, so without this a
       LiteLLM proxy serving ``ollama/glm-5.2`` would be silently reassigned to openrouter.
       Matching only that syntax (not ``startswith("custom")``) avoids swallowing
       unconfigured vendors like ``customproxy``.
    2. Model-format normalization for the resolved provider via
       ``normalize_model_for_provider`` (custom/user providers keep the model verbatim).
    """
    from hermes_cli.config import load_config
    from hermes_cli.config import get_compatible_custom_providers
    from hermes_cli.models import _AGGREGATOR_PROVIDERS, _KNOWN_PROVIDER_NAMES, normalize_provider
    from hermes_cli.model_normalize import normalize_model_for_provider
    from hermes_cli.providers import resolve_custom_provider, resolve_user_provider

    prov_in = (provider or "").strip()
    model_in = (model or "").strip()
    canonical = normalize_provider(prov_in)

    try:
        cfg = load_config()
    except Exception:  # health: allow BLE001 -- normalization falls back to an empty config; the caller still writes
        cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}
    user_providers = cfg.get("providers")
    declared = resolve_user_provider(
        prov_in, user_providers if isinstance(user_providers, dict) else {}
    ) or resolve_custom_provider(prov_in, get_compatible_custom_providers(cfg))
    if declared is not None:
        return declared.id, model_in

    is_custom_provider_slug = canonical == "custom" or canonical.startswith("custom:")
    if canonical not in _KNOWN_PROVIDER_NAMES and not is_custom_provider_slug and "/" in model_in:
        try:
            cur_cfg = cfg.get("model", {})
            cur_provider = (
                str(cur_cfg.get("provider", "") or "").strip().lower() if isinstance(cur_cfg, dict) else ""
            )
        except Exception:  # health: allow BLE001 -- unreadable model block = no current aggregator, not a failed write
            cur_provider = ""
        if cur_provider and normalize_provider(cur_provider) in _AGGREGATOR_PROVIDERS:
            canonical = normalize_provider(cur_provider)
            prov_in = cur_provider
        else:
            from hermes_cli.models_detect import provider_has_credentials

            # Only guess OpenRouter when the user actually holds a key for it; otherwise keep the
            # pair as sent rather than persisting a provider they never selected.
            if provider_has_credentials("openrouter"):
                canonical = prov_in = "openrouter"

    if canonical in _KNOWN_PROVIDER_NAMES and not canonical.startswith("custom"):
        try:
            model_in = normalize_model_for_provider(model_in, canonical) or model_in
        except Exception:  # health: allow BLE001 -- cosmetic normalization; the submitted model stays verbatim
            _log.debug("model normalization failed for %s/%s", prov_in, model_in, exc_info=True)

    return prov_in, model_in


_BARE_CUSTOM_SELECTORS = frozenset({"custom", "local"})


def _same_endpoint(a: Any, b: Any) -> bool:
    """Trailing-slash and case insensitive URL equality (custom-provider save dedups the same way)."""
    return str(a or "").strip().rstrip("/").lower() == str(b or "").strip().rstrip("/").lower()


def _entry_points_elsewhere(entry: Any, base_url: str) -> bool:
    """A configured provider block that names a DIFFERENT host than the submitted endpoint. Its
    credentials belong to that host; a block for the same host (e.g. its ``key_env``) still applies."""
    return isinstance(entry, dict) and not _same_endpoint(entry.get("base_url"), base_url)


def _is_explicit_custom_endpoint(provider: str, base_url: str) -> bool:
    """A bare ``custom`` / ``local`` pick that carries its own endpoint URL defines a route; it is
    never a reference to an already-configured provider."""
    return provider.strip().lower() in _BARE_CUSTOM_SELECTORS and bool((base_url or "").strip())


def _validated_main_model_selection(
    cfg: dict, provider: str, model: str, base_url: str = "", api_key: str = "",
    explicit_endpoint: Optional[bool] = None,
) -> ModelSwitchResult:
    """Route a main-slot pick through ``switch_model`` (catalog/alias/credential validation)
    seeded with the configured route, exactly like a ``/model <model> --provider <provider>
    --global``. A bare ``custom`` target carries the submitted endpoint as the current one,
    which is how ``switch_model`` binds a custom base_url/key. Rejections become
    :class:`MainModelRejected`."""
    from hermes_cli.config import get_compatible_custom_providers
    from hermes_cli.model_switch import switch_model

    model_cfg = cfg.get("model") if isinstance(cfg.get("model"), dict) else {}
    is_bare_custom = provider.strip().lower() in {"custom", "local"}
    # An explicit endpoint must not resolve through the configured providers: the legacy
    # bare-``custom`` recovery in ``resolve_custom_provider`` would bind the FIRST named entry, and
    # a ``providers.custom`` / ``providers.local`` block (same key as the bare selector) would win
    # the credential step and validate ITS host with ITS key. ``_prepare_main_assignment`` passes
    # whether the URL was SUBMITTED; a URL it filled from that block is a selection, not a route.
    if explicit_endpoint is None:
        explicit_endpoint = _is_explicit_custom_endpoint(provider, base_url)
    user_providers = cfg.get("providers") if isinstance(cfg.get("providers"), dict) else {}
    if explicit_endpoint:
        user_providers = {k: v for k, v in user_providers.items()
                          if not (str(k).strip().lower() in _BARE_CUSTOM_SELECTORS
                                  and _entry_points_elsewhere(v, base_url))}
    # The submitted endpoint is seeded as a current bare-``custom`` route so the credential step
    # keeps it: arriving from another provider it re-resolves ``custom`` from config and would
    # validate the saved ``model.base_url`` (and its key) instead of the endpoint being saved.
    result = switch_model(
        raw_input=model, explicit_provider=provider, is_global=True,
        current_provider="custom" if explicit_endpoint else str(model_cfg.get("provider") or ""),
        current_model=str(model_cfg.get("default") or ""),
        current_base_url=base_url if is_bare_custom else str(model_cfg.get("base_url") or ""),
        current_api_key=api_key if is_bare_custom else "",
        user_providers=user_providers,
        custom_providers=[] if explicit_endpoint else get_compatible_custom_providers(cfg))
    if not result.success:
        raise MainModelRejected(result.error_message or "model switch rejected")
    if is_bare_custom and base_url.strip():
        # The submitted endpoint IS the route this pick asked for; the credential step may have
        # re-resolved the bare target onto an env/config endpoint (CUSTOM_BASE_URL, a stale
        # model.base_url, the OPENROUTER_BASE_URL mirror). Restore the submitted endpoint AND the
        # wire protocol it mandates: ``model.base_url`` and ``model.api_mode`` are persisted
        # together, so a mode derived from the displaced host would route the submitted endpoint
        # over the wrong wire.
        from hermes_cli.providers import determine_api_mode
        url = base_url.strip()
        result = replace(result, base_url=url,
                         api_mode=determine_api_mode(result.target_provider, url))
    return result


def drop_model_key(model_cfg: dict, key: str) -> None:
    """Remove *key* from a ``model`` block an assignment is building. Under Remote Config the block
    is the EFFECTIVE one, so a key it holds may be inherited from an upper level that a profile
    removal cannot reach (contract §5.4); store null ("no value") instead, the same mask
    :func:`hermes_cli.model_switch.apply_model_selection` applies. A key the block lacks stays
    absent. File backend: a plain removal."""
    from hermes_cli.config_backend import supports_file_tooling
    if key not in model_cfg:
        return
    if supports_file_tooling():
        model_cfg.pop(key, None)
    else:
        model_cfg[key] = None


def _apply_main_model_assignment(model_cfg: Any, result: ModelSwitchResult, api_key: str = "") -> dict:
    """Apply a main-slot selection to a ``model`` config dict via the canonical /model shape
    (``hermes_cli.model_switch.apply_model_selection``). An explicit key for a custom endpoint is
    the one inline credential the runtime reads (``model.api_key``); the legacy ``api`` alias is
    dropped so a stale secret cannot shadow it.

    Returns a new dict."""
    from hermes_cli.config_backend import supports_file_tooling
    from hermes_cli.model_switch import apply_model_selection, remote_model_selection_guard

    before = model_cfg
    # Remote Config: the caller saves the effective block as a whole document, so a cleared
    # inherited key must be masked (null), and a locked route key refuses the whole assignment.
    model_cfg = apply_model_selection(model_cfg, result, mask_cleared=not supports_file_tooling())
    if api_key.strip():
        model_cfg["api_key"] = api_key.strip()
        drop_model_key(model_cfg, "api")
    remote_model_selection_guard(before, model_cfg)
    return model_cfg


def _provider_entry(cfg: dict, provider: str) -> Any:
    providers_cfg = cfg.get("providers")
    return providers_cfg.get(provider) if isinstance(providers_cfg, dict) else None


def _prepare_main_assignment(cfg: dict, provider: str, model: str, base_url: str, api_key: str) -> tuple[str, ModelSwitchResult]:
    """Validation half of a main-slot assignment: ``(effective base_url, switch result)``.
    ``switch_model`` fetches catalogs / probes endpoints, so callers run this BEFORE taking
    ``CONFIG_MUTATION_LOCK``; it writes nothing."""
    if not provider or not model:
        raise MainModelRejected("provider and model required for main")
    explicit_endpoint = _is_explicit_custom_endpoint(provider, base_url)
    if explicit_endpoint:
        # The Local / custom endpoint wizard: the submitted URL IS the route. Normalizing would
        # recover a bare ``custom`` onto the first named custom provider and keep ITS URL.
        provider, model = provider.strip(), model.strip()
    else:
        provider, model = _normalize_main_model_assignment(provider, model)
    provider_entry = _provider_entry(cfg, provider)
    if not base_url and isinstance(provider_entry, dict) and provider_entry.get("base_url"):
        base_url = str(provider_entry.get("base_url") or "").strip()
    return base_url, _validated_main_model_selection(
        cfg, provider, model, base_url, api_key, explicit_endpoint=explicit_endpoint)


def _resolve_assignment_credentials(model_cfg: dict, provider: str, provider_entry: Any) -> None:
    """Carry the provider's credential POINTER (``key_env`` / raw ``${VAR}``) onto ``model_cfg``.

    ``provider_entry`` comes from ``load_config()``, which expands ``${VAR}`` to plaintext;
    copying that into ``model.api_key`` would write the SECRET into config.yaml (and recreate
    it on every re-apply). Prefer the raw template; fall back to the expanded value only when
    the raw yaml itself stores the key as a literal (no new exposure).
    """
    from hermes_cli.config import find_provider_entry, read_raw_config
    try:
        _stored, raw_entry = find_provider_entry(read_raw_config().get("providers"), provider)
    except Exception:  # health: allow BLE001 -- no raw template: fall back to the expanded entry in hand
        raw_entry = None
    if not isinstance(raw_entry, dict):
        raw_entry = {}
    key_env = str(raw_entry.get("key_env") or "").strip()
    if key_env:
        model_cfg["key_env"] = key_env
        # Carry the credential POINTER, never a resolved secret. Masked, not dropped, under
        # Remote Config: an inherited inline key outranks key_env at runtime.
        drop_model_key(model_cfg, "api_key")
    elif isinstance(provider_entry, dict) and provider_entry.get("api_key"):
        raw_key = str(raw_entry.get("api_key") or "").strip()
        model_cfg["api_key"] = raw_key if raw_key.startswith("${") and raw_key.endswith("}") else provider_entry["api_key"]


def _apply_nous_gateway_defaults(cfg: dict) -> list:
    """Mirror the CLI's post-model-selection behaviour when switching main to Nous: route
    *unconfigured* tools through the Nous Tool Gateway. Purely additive — tools with a direct
    key or explicit backend are skipped. Failures never block saving the assignment."""
    try:
        from hermes_cli.nous_subscription import apply_nous_managed_defaults
        from hermes_cli.tools_config import _get_platform_tools

        enabled = _get_platform_tools(cfg, "cli", include_default_mcp_servers=False)
        return sorted(apply_nous_managed_defaults(cfg, enabled_toolsets=enabled, force_fresh=True))
    except Exception:  # health: allow BLE001 -- additive gateway defaults must never block the assignment
        _log.debug("apply_nous_managed_defaults skipped", exc_info=True)
        return []


def _endpoint_known_to_config(cfg: dict, base_url: str) -> bool:
    """True when *base_url* is already an endpoint fact in *cfg*: the inline ``model.base_url``,
    a ``providers.<slug>`` entry, or a ``custom_providers`` row. Comparison is trailing-slash
    and case insensitive."""
    wanted = str(base_url or "").strip().rstrip("/").lower()
    if not wanted:
        return False

    def _matches(value: Any) -> bool:
        return str(value or "").strip().rstrip("/").lower() == wanted

    model_cfg = cfg.get("model")
    if isinstance(model_cfg, dict) and _matches(model_cfg.get("base_url")):
        return True
    for section_key in ("providers", "custom_providers"):
        section = cfg.get(section_key)
        entries: Any = section if isinstance(section, list) else (
            list(section.values()) if isinstance(section, dict) else [])
        for entry in entries:
            if isinstance(entry, dict) and _matches(entry.get("base_url") or entry.get("url") or entry.get("api")):
                return True
    return False


def _register_custom_endpoint(base_url: str, api_key: str, model: str) -> None:
    """Register a named ``custom_providers`` entry for a custom/local endpoint (mirrors the
    ``hermes model`` custom flow) so the picker gets a proper ready row instead of a "needs
    setup" dead-end. Dedups by base_url; never blocks the already-persisted assignment.

    SKIPPED when the endpoint is already a fact in the config: re-registering a CLI-written
    inline ``provider: custom`` endpoint as a named ``custom:<slug>`` row on every re-save is
    what let the picker rewrite the CLI's shape."""
    try:
        from hermes_cli.main_provider_setup import _auto_provider_name, _save_custom_provider

        _save_custom_provider(base_url, api_key, model, name=_auto_provider_name(base_url))
    except Exception:  # health: allow BLE001 -- additive registration must never block the already-saved assignment
        _log.debug("custom_providers registration skipped", exc_info=True)


# Canonical auxiliary task slots. Keep in sync with DEFAULT_CONFIG["auxiliary"]
# in hermes_cli/config.py — listed here for deterministic ordering.
_AUX_TASK_SLOTS: tuple[str, ...] = (
    "vision", "compression", "approval", "mcp", "title_generation", "review", "voice_chat",
    "triage_specifier", "kanban_decomposer", "profile_describer", "curator",
)


def _plugin_aux_tasks() -> list[dict[str, Any]]:
    """Auxiliary tasks registered by plugins (``PluginContext.register_auxiliary_task``) for the
    Hermes home active in this context.

    Callers run inside ``config_profile_scope``, and ``get_plugin_manager()`` keys its manager on
    the same context-local home, so a request for profile B enumerates B's plugins even though
    this process was started for profile A. Discovery failure is fail-soft."""
    try:
        from hermes_cli.plugins import get_plugin_auxiliary_tasks
        return [dict(entry) for entry in get_plugin_auxiliary_tasks()
                if entry.get("key") and entry["key"] not in _AUX_TASK_SLOTS]
    except Exception:  # health: allow BLE001 -- plugin discovery must never break the built-in slots
        _log.debug("plugin auxiliary task lookup failed", exc_info=True)
        return []


def _aux_task_slots() -> tuple[str, ...]:
    """Every auxiliary slot a caller may read or assign: built-ins first, then plugin keys. The
    picker in ``hermes model`` folds plugin tasks in the same way."""
    return _AUX_TASK_SLOTS + tuple(entry["key"] for entry in _plugin_aux_tasks())


def _stale_aux_pins(cfg: dict, new_provider: str) -> list:
    """Aux slots still pinned to a *different* provider than the new main one.

    Switching main never touches aux pins (independent, sticky per-task overrides) — a user
    leaving a now-unpaid provider keeps paying 402s on background calls until they reset
    them. We never auto-clear (pinning aux is legitimate) but report them so a caller can
    offer a "reset to main" nudge.
    """
    from agent.model_metadata import is_local_endpoint

    stale_aux: list[dict] = []
    aux_cfg = cfg.get("auxiliary", {})
    if not isinstance(aux_cfg, dict):
        return stale_aux
    for slot in _aux_task_slots():
        slot_cfg = aux_cfg.get(slot)
        if not isinstance(slot_cfg, dict):
            continue
        slot_provider = str(slot_cfg.get("provider", "") or "").strip()
        # "main" is an alias for the active main provider (auxiliary_client._normalize_aux_provider):
        # it follows the switch and is never a stale pin.
        if slot_provider and slot_provider.lower() not in {"auto", "", "main"} and slot_provider.lower() != new_provider:
            # A pin on a private/LAN endpoint (per-task base_url, e.g. a home Ollama box) never bills
            # a provider, so a main switch does not orphan it.
            if is_local_endpoint(str(slot_cfg.get("base_url", "") or "")):
                continue
            stale_aux.append({
                "task": slot, "provider": slot_provider, "model": str(slot_cfg.get("model", "") or ""),
            })
    return stale_aux


def _apply_main_assignment_sync(cfg: dict, provider: str, model: str, base_url: str, api_key: str,
                                prepared: Optional[tuple[str, ModelSwitchResult]] = None) -> dict:
    """Write a prepared main-slot assignment into *cfg* and save it."""
    from hermes_cli.config import save_config
    from hermes_cli.config_backend import refusing_locked_omissions
    from hermes_cli.free_tier_bootstrap import reconcile_record
    # Recorded from the SUBMITTED args, before preparation fills a URL from a named entry.
    explicit_endpoint = _is_explicit_custom_endpoint(provider, base_url)
    base_url, result = prepared or _prepare_main_assignment(cfg, provider, model, base_url, api_key)
    provider, model = result.target_provider, result.new_model
    provider_entry = _provider_entry(cfg, provider)
    # Snapshot BEFORE the new assignment overwrites cfg["model"]: this is the state the user
    # already had on disk, and it decides whether the endpoint is genuinely NEW (register a
    # named custom_providers row) or already known (keep the existing shape).
    provider_lc = provider.strip().lower()
    endpoint_already_known = (
        provider_lc in {"custom", "local"} and bool(base_url) and _endpoint_known_to_config(cfg, base_url))
    model_cfg = _apply_main_model_assignment(cfg.get("model", {}), result, api_key)
    if not (explicit_endpoint and _entry_points_elsewhere(provider_entry, base_url)):
        # A submitted endpoint carries its own key (or none); a ``providers.custom`` block for
        # ANOTHER host shares the selector's name, and hydrating from it would pair the new URL with
        # that host's key. A block for the same host (its ``key_env``) still supplies the credential.
        _resolve_assignment_credentials(model_cfg, provider, provider_entry)
    cfg["model"] = model_cfg

    new_provider = provider.strip().lower()
    gateway_tools = _apply_nous_gateway_defaults(cfg) if new_provider == "nous" else []
    # One route: a model.* key locked by the time the save runs (even after the preflight guard
    # above, or on its CAS retry) refuses the whole save instead of being omitted from it.
    with refusing_locked_omissions("model"):
        save_config(cfg)
    if new_provider in {"custom", "local"} and base_url and not endpoint_already_known:
        _register_custom_endpoint(base_url, api_key, model)
    # The process's boot record may still say "nothing configured"; the chat gates on it.
    reconcile_record()

    return {
        "ok": True,
        "scope": "main",
        "provider": provider,
        "model": model,
        "base_url": model_cfg.get("base_url", ""),
        "gateway_tools": gateway_tools,
        "stale_aux": _stale_aux_pins(cfg, new_provider),
        # Window plans, Large model: the warning (never a confirm). Absent for everyone else.
        **({"notice": result.usage_notice} if getattr(result, "usage_notice", "") else {}),
    }


def assign_main_model(provider: str, model: str, base_url: str = "", api_key: str = "") -> dict:
    """Apply a main-slot model assignment to the ACTIVE profile's config.yaml.

    The caller binds the profile's home/secret scope (``config_profile_scope``) around this call
    when the target is not the process's own profile. Returns the assignment result (the shape
    the dashboard's ``POST /api/model/set`` returned)."""
    from hermes_cli.config import load_config
    return _apply_main_assignment_sync(load_config(), provider, model, base_url, api_key)


def write_profile_model(profile_dir, provider: str, model: str, validate_in=None,
                        base_url: str = "") -> None:
    """Write the main model assignment into ``profile_dir``'s config.yaml (HERMES_HOME-scoped)
    through the same validated /model shape as ``POST /api/model/set``.

    ``validate_in`` is the home whose ``providers:``/``.env``/catalog vouch for the pick (default:
    ``profile_dir`` itself). Profile-create passes the process home: the picker that offered
    the model read THAT catalog, and a just-created profile has no credentials yet, so validating
    in the empty profile rejected every non-env provider (anthropic, ollama, custom).

    Both spans enter :func:`config_profile_scope` (home + secret scope), matching ``/api/model/set``:
    once a secondary profile has been served, ``switch_model``'s ``key_env`` probe goes
    through ``get_secret``, which fails closed without a scope and reports the provider as
    unconnected (UnscopedSecretError class).

    ``base_url`` is the endpoint a bare ``custom``/``local`` pick binds to (a fresh profile's config
    names none); other providers ignore it."""
    from hermes_cli.config import load_config, save_config
    from hermes_cli.config_backend import refusing_locked_omissions
    with config_profile_scope(scope_profile_name(validate_in or profile_dir)):
        provider, model = _normalize_main_model_assignment(provider, model)
        result = _validated_main_model_selection(load_config(), provider, model, base_url)
    with config_profile_scope(scope_profile_name(profile_dir)), CONFIG_MUTATION_LOCK:  # RMW span
        cfg = load_config()
        cfg["model"] = _apply_main_model_assignment(cfg.get("model", {}), result)
        with refusing_locked_omissions("model"):
            save_config(cfg)
