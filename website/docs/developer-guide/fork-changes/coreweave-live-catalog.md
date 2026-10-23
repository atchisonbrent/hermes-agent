# CoreWeave provider-qualified metadata

Classification: upstream-candidate
Upstream base: upstream/main cb757fac59c92b49e9b8f2910e5cd7ab75efffdd; implementation on reviewed fork baseline d64c575b95c90cb6add6cd272816e019385d627a.
Problem: CoreWeave uses the custom OpenAI-compatible transport, but context resolution loses provider identity; MiniMax M3's model-family correction can override another provider's smaller serving limit. Capability objects also discard published effort options.
Reproduction: configure the CoreWeave endpoint and resolve its runtime route, then call get_model_context_length with the returned provider=custom. See tests/agent/test_configured_catalog_metadata.py, including exact-host/lookalike boundaries and provider-specific MiniMax M3 context.
Expected: CoreWeave's own catalog context, not the upstream vendor's larger window; optional graded effort values distinguish absent metadata from no graded control.
Actual: unknown-endpoint/family fallback and a broad native MiniMax correction can override the serving-provider limit.
Root cause: missing exact-host/provider identity and a vendor-specific correction scoped by model name alone.
Change: stable wandb catalog identity, exact CoreWeave hostname recognition, exclusion of CoreWeave from the existing MiniMax correction, and optional reasoning_options parsing on ModelCapabilities. No model catalog or network scheduler is added.
Verification: Targeted Agent metadata tests pass across metadata, catalog, local context and route mismatch. Isolated live integration used resolve_runtime_provider(requested=wandb) and matched all 23 provider contexts against current metadata; MiniMax M3 resolved to 262144. Tests do not certify full-window inference quality.
Compatibility / risk: URL-inferred identity uses the exact serving hostname (not scheme/port); proxy/lookalike URLs do not inherit it. Explicit provider=wandb selects its capability catalog and provider-aware context stage; an unknown/proxy endpoint still takes the existing earlier live probe. Explicit custom:<name> identities retain their declared catalog_provider even when the name collides with a known key; an undeclared custom alias does not inherit that key. The M3 exception follows resolved catalog identity, including declared CoreWeave aliases. Existing ModelCapabilities fields remain unchanged; effort metadata is additive. Existing MiniMax correction remains in place for every other provider; native MiniMax and Novita are positive controls. The unused coreweave alias is not added. URL identity also feeds existing route-mismatch and cost-guard consumers; no endpoint/key selection changes.
Maintenance owner: fork maintainers; rebase surface agent/model_metadata.py and agent/models_dev.py.
Rollback: revert this logical change and restore explicit provider context settings in dependent configuration before activation; no state migration.
Upstream status: issue-ready, not filed. Public catalog source https://models.dev/api.json; provider source https://docs.coreweave.com/products/inference/serverless/models .
Private details removed: yes.
