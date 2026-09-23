from fastapi import FastAPI

from backend import __version__


def create_app() -> FastAPI:
    app = FastAPI(title="HACKALEM procurement", version=__version__)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
