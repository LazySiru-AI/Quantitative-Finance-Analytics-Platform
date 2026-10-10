"""On-display Korean translation for model-written narrative prose.

Phase 4 of the i18n rollout: a config-gated (`Settings.translate_narratives`, default `False`)
service that translates English narrative sentences to Korean via `app.agents.client.call_structured`,
rejects any translation that drops or alters a source number (`app.agentdesk.grounding.numeric_tokens`
is the same gate the grounding layer already uses), and caches accepted translations to disk so the
same sentence is never paid for twice. See `app.i18n.narrative` for the service and `app.i18n.cache`
for the persistent store; `app.api.i18n` is the HTTP surface both sit behind.
"""

from __future__ import annotations
