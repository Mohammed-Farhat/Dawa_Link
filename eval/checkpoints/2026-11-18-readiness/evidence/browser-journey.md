# Native Safari journey, 2026-11-18

Browser connector unavailable; native Safari successfully used through CUA.
Dedicated http://localhost:55173 -> localhost:58000, evaluation PostgreSQL only.
Script: browser_app.py, original agent/API with injected ScriptedModel and clock.
Synthetic client02 login -> wrote request -> clarification question displayed ->
answered today/seven days/car -> reserve proposal displayed -> clicked Reserve ->
R-8DQTK3 saved -> logged into pharmacy02 -> Today page listed R-8DQTK3 ->
clicked row -> Picked up -> observed "Picked up" and zero due/packs reserved.
Tool outputs in session document every accessibility state. API logs retained.
Fixture chooses an available listing; it verifies transport/cards/approval/pickup,
not understanding or clinical selection. No model API calls during this journey.

Failure observed: clicking client Log out returned HTTP 204 server-side but page
remained /me, retaining profile UI and retrying requests with invalid token (401).
A browser refresh returned /login. No product fix applied; keep separate from
architecture work. Native browser cancellation/unavailable/sourcing-timeout journeys
remain incomplete; automated service/API tests passed for these behaviors.
Password-saving prompts dismissed with Not Now. Existing browser tabs preserved.
