"""CLI entry point for ly-next."""

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="LY-Next - FastAPI + LangGraph Agent Framework")
    parser.add_argument(
        "action",
        nargs="?",
        default="run",
        choices=["run", "dev", "shell"],
        help="Action to perform",
    )
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--reload", action="store_true")

    args, unknown = parser.parse_known_args()

    if args.action in ("run", "dev"):
        cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "ly_next.main:app",
            "--host",
            args.host or "0.0.0.0",
            "--port",
            str(args.port or 8000),
        ]
        if args.action == "dev" or args.reload:
            cmd.append("--reload")
        cmd.extend(unknown)

        env = dict(__import__("os").environ)
        env["PYTHONPATH"] = str(Path(__file__).parent)

        subprocess.run(cmd, env=env)

    elif args.action == "shell":
        from ly_next.core.cache import cache
        from ly_next.core.config import config
        from ly_next.core.database import db

        async def shell():
            print("LY-Next Shell")
            print("=" * 40)

            await db.connect()
            await cache.connect()

            print("Database: Connected")
            print("Redis: Connected")
            print("\nCommands: db, cache, config, quit")

            while True:
                try:
                    cmd = input("> ").strip()
                    if cmd == "quit":
                        break
                    elif cmd == "db":
                        print(f"Database URL: {config.database_url}")
                    elif cmd == "cache":
                        print(f"Redis URL: {config.redis_url}")
                    elif cmd == "config":
                        import json

                        print(json.dumps(config.to_dict(), indent=2))
                    else:
                        print(f"Unknown command: {cmd}")
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    print(f"Error: {e}")

            await db.disconnect()
            await cache.disconnect()
            print("Goodbye!")

        asyncio.run(shell())


if __name__ == "__main__":
    main()
