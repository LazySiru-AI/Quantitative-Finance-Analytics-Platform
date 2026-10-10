"""Local, privacy-light usage telemetry.

Unrelated to `app.agentdesk.telemetry` (model-call cost accounting) or `app.workflow.telemetry`
(workflow-run cost accounting) despite the shared name -- those live under their own feature
packages because they are about spend, not navigation. This package holds exactly one thing so far:
`nav`, the SPA route-change hit log behind the Data > Health "Navigation" table.
"""

from __future__ import annotations
