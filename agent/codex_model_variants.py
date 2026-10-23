"""Hermes-only Codex model route suffixes that never reach the provider wire."""

from __future__ import annotations

from typing import Optional

CODEX_DAYBREAK_BLUE_SUFFIX = "-daybreak-blue"


def bare_codex_slug(model: Optional[str]) -> str:
    """Lowercased slug without a vendor namespace."""
    return (model or "").strip().lower().rsplit("/", 1)[-1]


def codex_access_program_for_model(model: Optional[str]) -> Optional[str]:
    """The explicit access program encoded by a Hermes picker route, if any."""
    slug = bare_codex_slug(model)
    if slug.startswith("gpt-daybreak-blue") or not slug.endswith(CODEX_DAYBREAK_BLUE_SUFFIX):
        return None
    base = slug[: -len(CODEX_DAYBREAK_BLUE_SUFFIX)]
    if not base:  # a bare suffix would produce an empty wire slug
        return None
    return "daybreak_blue"


def validate_codex_access_route(
    route_model: Optional[str], selected_model: Optional[str], *, model_overridden: bool,
    is_codex_backend: bool,
) -> Optional[str]:
    """Resolve an explicit access route or fail before it can silently change policy mode."""
    route_program = codex_access_program_for_model(route_model)
    program = codex_access_program_for_model(selected_model)
    if route_program and model_overridden and not program:
        raise ValueError(
            "A model override cannot silently downgrade an explicit Daybreak Blue route; "
            "override with another `-daybreak-blue` route or disable the override."
        )
    if program and not is_codex_backend:
        raise ValueError(
            "Daybreak Blue routes are supported only on the authenticated ChatGPT Codex backend; "
            "refusing to strip the route and run it as a standard model on this Responses endpoint."
        )
    return program


def strip_codex_access_program_suffix(model: Optional[str]) -> str:
    """Remove a recognized Hermes access-program suffix while preserving any vendor namespace."""
    raw = (model or "").strip()
    return raw[: -len(CODEX_DAYBREAK_BLUE_SUFFIX)] if codex_access_program_for_model(raw) else raw


def codex_access_program_request_fields(
    model: Optional[str], *, is_codex_backend: bool,
) -> dict[str, object]:
    """Auxiliary Responses fields for an explicit access route, failing closed off Codex."""
    program = codex_access_program_for_model(model)
    if not program:
        return {}
    if not is_codex_backend:
        raise ValueError(
            "Daybreak Blue auxiliary routes require the authenticated ChatGPT Codex backend."
        )
    return {"extra_body": reconcile_codex_access_program_extra_body(None, program)}


def reconcile_codex_access_program_extra_body(
    extra_body: object, access_program: Optional[str],
) -> Optional[dict[str, object]]:
    """Copy request extras, enforcing explicit-route ownership of the ``cyber`` dimension."""
    if not access_program and not isinstance(extra_body, dict):
        return None
    body = dict(extra_body) if isinstance(extra_body, dict) else {}
    raw_programs = body.get("access_programs")
    programs = dict(raw_programs) if isinstance(raw_programs, dict) else {}
    if access_program:
        programs["cyber"] = access_program
    else:
        programs.pop("cyber", None)
    if programs:
        body["access_programs"] = programs
    else:
        body.pop("access_programs", None)
    return body


def codex_access_program_cache_identity(text: str, model: Optional[str]) -> str:
    """Keep standard and access-program prompt-cache routing distinct."""
    program = codex_access_program_for_model(model)
    return f"{text}\0access_program={program}" if program else text
