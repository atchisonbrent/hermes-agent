"""Local capacity accounting for the no-tools durable-write reviewer.

No network, credentials, inference, or persistent caches are used in preflight.
"""

from agent.model_metadata import (
    _CODEX_OAUTH_CONTEXT_FALLBACK,
)

# I/O/memory bound, not a model context window. The model-token budget is separate.
MAX_PACKET_BYTES = 16 * 1024 * 1024


def model_capacity(model):
    """Use the existing Codex-route catalog, not direct-API or interactive limits."""
    window = _CODEX_OAUTH_CONTEXT_FALLBACK.get(model)
    source = "exact Codex-route fallback catalog"
    if type(window) is not int or window <= 8192:
        return None
    # Reserve at least 8192 tokens and 20% of the window for output, reasoning,
    # wire framing and estimator error. This is not a provider output-token cap.
    return {"context_tokens": window, "max_input_tokens": window - max(8192, window // 5),
            "context_source": source}


def packet_tokens(policy, encoded_context):
    # Deliberately more conservative than the general ASCII chars/4 estimate.
    # This remains an estimate, not a tokenizer or proof of provider fit; the
    # reserved context margin and fail-closed API boundary remain necessary.
    # Do not retain entire packets in the global message-estimator cache.
    size = len(policy.encode("utf-8")) + len(encoded_context.encode("utf-8"))
    return (size + 2) // 3 + 32
