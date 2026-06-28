"""Web UI — the substitution builder (build step 4; FastAPI + HTMX + Jinja).

The surface for CLAUDE.md §1's funnel: pick a commander, browse curated EDHREC
decks, substitute cards with live win-condition + bracket feedback, export a
`.dck` for XMage. The pipeline stays headless-importable; this package and its
deps (the `web` extra) sit on top of it.
"""
