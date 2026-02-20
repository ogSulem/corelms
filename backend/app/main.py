import uuid
import time
import json
import logging
import threading
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.redis_client import get_redis
from app.core.queue import get_queue
from app.services.storage_cleanup_jobs import cleanup_admin_uploads_job
from app.routers import admin, assets, auth, health, linear, me, modules, progress, quizzes, submodules

def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    app = FastAPI(title="CoreLMS API", version="1.0.0")

    logger = logging.getLogger("corelms")

    try:
        logging.getLogger("httpx").setLevel(logging.WARNING)
    except Exception:
        pass

    allow_origins = [o.strip() for o in str(settings.cors_allow_origins or "").split(",") if o.strip()]
    if "*" in allow_origins:
        raise RuntimeError("CORS_ALLOW_ORIGINS must not include '*' when allow_credentials=true")

    is_prod = (settings.app_env or "").strip().lower() in {"prod", "production"}

    def _parse_csv(value: str) -> list[str]:
        return [x.strip() for x in str(value or "").split(",") if x.strip()]

    allow_methods_raw = str(getattr(settings, "cors_allow_methods", "*") or "*").strip()
    allow_headers_raw = str(getattr(settings, "cors_allow_headers", "*") or "*").strip()
    if is_prod:
        if allow_methods_raw == "*":
            allow_methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
        else:
            allow_methods = _parse_csv(allow_methods_raw)

        if allow_headers_raw == "*":
            allow_headers = ["authorization", "content-type", "x-request-id"]
        else:
            allow_headers = _parse_csv(allow_headers_raw)
    else:
        allow_methods = ["*"] if allow_methods_raw == "*" else _parse_csv(allow_methods_raw)
        allow_headers = ["*"] if allow_headers_raw == "*" else _parse_csv(allow_headers_raw)

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        t0 = time.perf_counter()
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = rid
        status_code: int | None = None
        try:
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                origin = (request.headers.get("origin") or "").strip()
                if origin and origin not in allow_origins:
                    from fastapi import HTTPException

                    raise HTTPException(status_code=403, detail="invalid origin")
            response = await call_next(request)
            status_code = int(getattr(response, "status_code", 0) or 0)
        except Exception:
            status_code = 500
            raise
        finally:
            try:
                dur_ms = int((time.perf_counter() - t0) * 1000)
                path = getattr(getattr(request, "url", None), "path", "")
                if not (
                    path.startswith("/health")
                    or path == "/healthz"
                    or path.startswith("/admin/jobs/")
                ):
                    logger.info(
                        json.dumps(
                            {
                                "ts": datetime.utcnow().isoformat(),
                                "rid": rid,
                                "user_id": getattr(getattr(request, "state", None), "user_id", None),
                                "method": request.method,
                                "path": path,
                                "status": status_code,
                                "duration_ms": dur_ms,
                            },
                            ensure_ascii=False,
                        )
                    )
            except Exception:
                pass
        response.headers["X-Request-ID"] = rid

        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        if (settings.app_env or "").strip().lower() in {"prod", "production"}:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    def _request_id(request: Request) -> str | None:
        rid = getattr(getattr(request, "state", None), "request_id", None)
        rid = str(rid or "").strip()
        return rid or None

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        rid = _request_id(request)
        detail = exc.detail
        if isinstance(detail, dict):
            error_code = str(detail.get("error_code") or "http_error")
            error_message = str(detail.get("error_message") or detail.get("detail") or "request failed")
        else:
            error_code = "forbidden" if int(exc.status_code) == 403 else "unauthorized" if int(exc.status_code) == 401 else "http_error"
            error_message = str(detail or "request failed")

        payload = {
            "ok": False,
            "error_code": error_code,
            "error_message": error_message,
            "request_id": rid,
        }
        return JSONResponse(status_code=int(exc.status_code), content=payload, headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        rid = _request_id(request)
        logger.exception("unhandled exception", extra={"rid": rid})
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error_code": "internal_error",
                "error_message": "internal server error",
                "request_id": rid,
            },
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=allow_methods,
        allow_headers=allow_headers,
    )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(quizzes.router)
    app.include_router(assets.router)
    app.include_router(me.router)
    app.include_router(modules.router)
    app.include_router(admin.router)
    app.include_router(progress.router)
    app.include_router(submodules.router)
    app.include_router(linear.router)

    def _start_admin_uploads_cleanup_scheduler() -> None:
        interval_seconds = max(60, int(settings.uploads_admin_cleanup_interval_minutes) * 60)

        def _tick() -> None:
            try:
                r = get_redis()
                lock_key = "locks:admin_uploads_cleanup"
                lock_ttl = max(60, interval_seconds - 5)

                acquired = r.set(lock_key, "1", nx=True, ex=int(lock_ttl))
                if not acquired:
                    return

                q = get_queue("corelms")
                q.enqueue(
                    cleanup_admin_uploads_job,
                    ttl_hours=int(settings.uploads_admin_ttl_hours),
                    job_timeout=60 * 10,
                    result_ttl=60 * 60,
                    failure_ttl=60 * 60,
                )
            except Exception:
                return
            finally:
                t = threading.Timer(interval_seconds, _tick)
                t.daemon = True
                t.start()

        t0 = threading.Timer(10, _tick)
        t0.daemon = True
        t0.start()

    @app.on_event("startup")
    async def _startup_tasks() -> None:
        if bool(getattr(settings, "enable_inprocess_scheduler", False)):
            _start_admin_uploads_cleanup_scheduler()

    return app

app = create_app()
