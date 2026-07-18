from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.database import engine, Base
from app.redis import get_redis, close_redis
from app.routers import sessions, tools, agent, nodes


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield
    await close_redis()


def create_app() -> FastAPI:
    app = FastAPI(title="Mini Agent Runtime", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(sessions.router)
    app.include_router(tools.router)
    app.include_router(agent.router)
    app.include_router(nodes.router)

    @app.get("/health")
    async def health():
        pg_ok = False
        redis_ok = False
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            pg_ok = True
        except Exception:
            pass
        try:
            r = await get_redis()
            await r.ping()
            redis_ok = True
        except Exception:
            pass
        return {"pg": "ok" if pg_ok else "fail", "redis": "ok" if redis_ok else "fail"}

    return app


app = create_app()
