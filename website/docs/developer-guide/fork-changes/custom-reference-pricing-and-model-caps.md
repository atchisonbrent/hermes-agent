# Custom reference pricing and model-specific compaction caps

Classification: upstream-candidate
Upstream base: retained fork base `bdba8062814d9acec5cd8e242fc5689e8d03b793`
Problem: private OpenAI-compatible models can have known reference rates but no price metadata, and a global compaction cost cap cannot be disabled for one inexpensive model.
Reproduction: configure per-model reference rates on a named custom provider; set a 75% model threshold alongside a lower global token cap.
Expected behavior: estimate equivalent value without asserting billing; allow an explicit model-specific cap exception without changing other models.
Change: profile-bound reference price lookup for unknown billing routes, plus exact model/route token-cap overrides. Provider actuals, included pricing, output reservation, auxiliary context ceilings and explicit delegated-child ceilings retain precedence.
Verification: targeted accounting, cost guard, compression, live config reload and delegated-child tests; native client qualification is required separately for a deployment.
Compatibility / risk: opt-in only. Reference pricing supports named `providers` blocks, not legacy `custom_providers`; historical cost rows are not backfilled. Model cap exceptions do not change plugin-owned context-engine policy. No private endpoint, credential, provider name or rate contract is compiled into source.
Maintenance owner: Brent Atchison / `atchisonbrent/hermes-agent` fork until upstream ships equivalent behavior.
Rollback: remove the model-cap exception first (restores global policy), then revert the implementation commits. Existing recorded costs remain intact; future custom costs return to unknown.
Upstream status: not submitted
Private details removed: yes

Retire these deltas when upstream provides compatible profile-local reference rates and per-model caps. No service, recurring job or additional network request is introduced.
