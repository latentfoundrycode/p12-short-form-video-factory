from fastapi import FastAPI


def create_app() -> FastAPI:
    application = FastAPI(title="Short-Form Video Factory")

    @application.get("/api/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    return application


app = create_app()
