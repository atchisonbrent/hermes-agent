# Mandatory W&B project attribution

## Fork-Only

Classification: fork-only
Reason: This fork's W&B inference traffic must always be charged to Brent's `cw-wb/storage` project. The project identifier is installation-specific and is not suitable for upstream defaults.

Implementation: OpenAI-compatible clients targeting the exact `api.inference.wandb.ai` host force `OpenAI-Project: cw-wb/storage` during main startup, main-client rebuilds, and synchronous/asynchronous auxiliary construction. Other hosts are unchanged. A case-insensitive conflicting project header is replaced.

Rollback: revert the associated commit; normal provider-configured `extra_headers` behavior remains available.
