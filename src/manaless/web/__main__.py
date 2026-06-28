"""``python -m manaless.web`` — run the substitution builder locally.

    python -m manaless.web [--host H] [--port P] [--reload]
"""

from __future__ import annotations


def main() -> None:
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Run the Manaless web UI (build step 4).")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="auto-reload on code changes (dev)")
    args = parser.parse_args()

    uvicorn.run("manaless.web.app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
