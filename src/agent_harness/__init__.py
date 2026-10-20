"""Harneasy package entry point."""
from dotenv import load_dotenv

# Must run before importing modules that initialize PROJECT_ROOT or limits.
load_dotenv()

def main() -> None:
    from .agent import main as run_agent

    run_agent()

__all__ = ["main"]
