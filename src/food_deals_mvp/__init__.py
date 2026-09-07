"""Local Telegram food deals processing."""

__all__ = ["main"]


def main() -> None:
    """Load pipeline modules only when invoking the processing CLI."""
    from .cli import main as cli_main

    cli_main()
