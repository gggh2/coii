"""CLI entry point: coii serve"""
import click
import uvicorn
import os


@click.group()
def main():
    """Coii — Open-source LLM experimentation platform."""
    pass


@main.command()
@click.option("--host", default="0.0.0.0", help="Bind host")
@click.option("--port", default=8080, help="Bind port")
@click.option("--database-url", default=None, help="Database URL (default: SQLite ./coii.db)")
@click.option("--reload", is_flag=True, help="Auto-reload on code changes")
def serve(host, port, database_url, reload):
    """Start the Coii server."""
    if database_url:
        os.environ["COII_DATABASE_URL"] = database_url
    
    click.echo(f"🚀 Coii server starting...")
    click.echo(f"   Dashboard: http://{host if host != '0.0.0.0' else 'localhost'}:{port}")
    click.echo(f"   API: http://{host if host != '0.0.0.0' else 'localhost'}:{port}/api/v1")
    click.echo(f"   Docs: http://{host if host != '0.0.0.0' else 'localhost'}:{port}/docs")
    
    uvicorn.run(
        "coii_server.app:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    main()
