# Custom endpoint reference pricing

Named `providers` entries can opt into per-model reference estimates for routes
whose billing mode is unknown/custom. Legacy `custom_providers` entries are not
supported by this opt-in. URL aliases use the runtime's precedence (`api`, `url`,
then `base_url`), and matching uses Hermes's normalized route identity. Different
non-default ports and API paths remain different endpoints. Model IDs are exact;
`models` may use mapping or list form. Prefer mapping form: dashboard saves can
discard list-row metadata, including prices. Use a simple hyphenated provider key,
not a built-in provider ID; built-in keys are excluded from this pricing opt-in.

```yaml
providers:
  internal:
    name: Internal inference
    base_url: http://inference.example.test:8000/v1
    default_model: served-model
    api_mode: chat_completions
    models:
      served-model:
        pricing:
          input_cost_per_million: 2
          output_cost_per_million: 10
          cache_read_cost_per_million: 0.20
          cache_write_cost_per_million: 2
```

All values are USD per million tokens, finite and between 0 and 1,000,000.
Input and output are required; absent cache prices remain unknown when that usage
is reported. Invalid or ambiguous entries are silently ignored and the existing
pricing lookup resumes. Disabled providers are not used. There is no model-level
disable switch in this setting. A valid configured rate takes precedence over
endpoint-advertised and models.dev rates for the matched custom route. Generic
`custom` runtime requests match
by endpoint and model; named requests additionally match the exact provider key
(`key` or `custom:key`), not its display-name alias.

These figures have source `user_override`, status `estimated`, and version
`configured-reference-v1`. They can represent standard API equivalent value for
an internally hosted model with no charge to the user. They are **not actual
spending or billing evidence**. Existing subscription-included and provider-
reported actual-cost handling retain precedence. Changing rates affects future
estimates, not a provider invoice. Persisted historical costs are not backfilled.
Insights can reclassify previously unknown sessions as having known pricing while
its dollar totals still omit their missing stored costs. Legacy usage rows without
stored cost status/source may be re-estimated using current rates. Do not treat
historical Insights flags or totals as a reconciled invoice.

Auxiliary accounting also requires the server's echoed model ID to match the
configured model key; an alias echoed by the server can leave that usage unknown.

Settings are read from the currently bound Hermes profile without a cross-profile
pricing cache. No endpoint, hostname or private contract is compiled into Hermes.
The model picker does not currently render these configured reference prices.
