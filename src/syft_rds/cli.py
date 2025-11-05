import typer

app = typer.Typer(
    name="syft-rds",
    help="Syft RDS - Remote Data Science with Privacy",
    pretty_exceptions_enable=False,
    rich_markup_mode=None,  # Disable rich formatting to avoid version conflicts
)


def show_info():
    """Show version information and getting started guide."""
    from syft_rds import __version__

    typer.echo(f"syft-rds version {__version__}")
    typer.echo()
    typer.secho("Getting Started:", fg=typer.colors.GREEN, bold=True)
    typer.echo("  Use Python to interact with Syft RDS:")
    typer.echo()
    typer.secho("    from syft_rds import init_session", fg=typer.colors.CYAN)
    typer.echo()
    typer.secho("    # For Data Owners:", fg=typer.colors.YELLOW)
    typer.secho("    client = init_session(", fg=typer.colors.CYAN)
    typer.secho("        host='do@example.com',", fg=typer.colors.CYAN)
    typer.secho("        email='do@example.com'", fg=typer.colors.CYAN)
    typer.secho("    )", fg=typer.colors.CYAN)
    typer.echo()
    typer.secho("    # For Data Scientists:", fg=typer.colors.YELLOW)
    typer.secho("    client = init_session(", fg=typer.colors.CYAN)
    typer.secho("        host='do@example.com',", fg=typer.colors.CYAN)
    typer.secho("        email='ds@example.com'", fg=typer.colors.CYAN)
    typer.secho("    )", fg=typer.colors.CYAN)
    typer.echo()
    typer.secho("Documentation:", fg=typer.colors.GREEN, bold=True)
    typer.echo("  https://docs.syftbox.openmined.org")


@app.callback(invoke_without_command=True)
def callback(ctx: typer.Context):
    """Show version and getting started information."""
    if ctx.invoked_subcommand is None:
        # No subcommand was invoked, show info
        show_info()


def main():
    app()


if __name__ == "__main__":
    main()
