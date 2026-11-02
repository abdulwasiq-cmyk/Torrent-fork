"""Offline structure check for the FastAPI app.

The sandbox this refactor is done in cannot install FastAPI, so this script
imports ``backend/main.py`` against tiny recording stand-ins for FastAPI,
httpx, libtorrent, cryptography, bs4 and pydantic, then prints the structure
that must not change while ``main.py`` is split up:

* the ordered route table (method, path, endpoint name)
* the middleware order
* exception handlers
* startup / shutdown hook order

CI checks the same structure against the real FastAPI app
(``backend/tests/test_app_structure.py``), so the snapshot in
``backend/tests/snapshots/app_structure.json`` is verified twice.

Usage (from the repository root)::

    python3 -I scripts/refactor/stubcheck.py            # print structure
    python3 -I scripts/refactor/stubcheck.py --write    # refresh the snapshot
    python3 -I scripts/refactor/stubcheck.py --check    # compare with snapshot
"""

from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
SNAPSHOT = BACKEND / "tests" / "snapshots" / "app_structure.json"


# --------------------------------------------------------------------------
# Generic "accept anything" stand-in for third-party libraries
# --------------------------------------------------------------------------
class _StubMeta(type):
    def __getattr__(cls, name):  # Fernet.generate_key, httpx.Timeout.something...
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return Stub()


class Stub(metaclass=_StubMeta):
    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        return Stub()

    def __getattr__(self, name):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return Stub()

    def __iter__(self):
        return iter(())

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __getitem__(self, item):
        return Stub()

    def __or__(self, other):
        return Stub()

    __ror__ = __or__


class _StubModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        cls = type(name, (Stub,), {})
        setattr(self, name, cls)
        return cls


class Route:
    def __init__(self, methods, path, endpoint):
        self.methods = set(methods)
        self.path = path
        self.endpoint = endpoint
        self.name = getattr(endpoint, "__name__", "")


class Middleware:
    def __init__(self, cls, **kwargs):
        self.cls = cls
        self.kwargs = kwargs


class APIRouter:
    def __init__(self, *args, **kwargs):
        self.routes: list[Route] = []
        self.on_startup: list = []
        self.on_shutdown: list = []

    def _route_decorator(self, methods):
        def decorator(path, *args, **kwargs):
            def wrap(fn):
                self.routes.append(Route(methods, path, fn))
                return fn

            return wrap

        return decorator

    def get(self, path, *a, **k):
        return self._route_decorator(["GET"])(path, *a, **k)

    def post(self, path, *a, **k):
        return self._route_decorator(["POST"])(path, *a, **k)

    def put(self, path, *a, **k):
        return self._route_decorator(["PUT"])(path, *a, **k)

    def delete(self, path, *a, **k):
        return self._route_decorator(["DELETE"])(path, *a, **k)

    def patch(self, path, *a, **k):
        return self._route_decorator(["PATCH"])(path, *a, **k)

    def head(self, path, *a, **k):
        return self._route_decorator(["HEAD"])(path, *a, **k)

    def options(self, path, *a, **k):
        return self._route_decorator(["OPTIONS"])(path, *a, **k)

    def api_route(self, path, methods=None, **k):
        return self._route_decorator(methods or ["GET"])(path)

    def include_router(self, router, **kwargs):
        self.routes.extend(router.routes)
        self.on_startup.extend(router.on_startup)
        self.on_shutdown.extend(router.on_shutdown)

    def add_event_handler(self, kind, fn):
        (self.on_startup if kind == "startup" else self.on_shutdown).append(fn)

    def on_event(self, kind):
        def wrap(fn):
            self.add_event_handler(kind, fn)
            return fn

        return wrap


class FastAPI(APIRouter):
    def __init__(self, *args, **kwargs):
        super().__init__()
        self.router = self
        self.user_middleware: list[Middleware] = []
        self.exception_handlers: dict = {}

    def add_middleware(self, cls, **kwargs):
        self.user_middleware.insert(0, Middleware(cls, **kwargs))

    def middleware(self, kind):
        def wrap(fn):
            self.add_middleware(type("BaseHTTPMiddleware", (), {}), dispatch=fn)
            return fn

        return wrap

    def exception_handler(self, exc):
        def wrap(fn):
            self.exception_handlers[getattr(exc, "__name__", str(exc))] = fn
            return fn

        return wrap


class HTTPException(Exception):
    def __init__(self, status_code=500, detail=None, headers=None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class CORSMiddleware:  # name matters: the structure records cls.__name__
    pass


def install_stubs() -> None:
    fastapi = _StubModule("fastapi")
    fastapi.FastAPI = FastAPI
    fastapi.APIRouter = APIRouter
    fastapi.HTTPException = HTTPException
    sys.modules["fastapi"] = fastapi

    cors = _StubModule("fastapi.middleware.cors")
    cors.CORSMiddleware = CORSMiddleware
    sys.modules["fastapi.middleware"] = _StubModule("fastapi.middleware")
    sys.modules["fastapi.middleware.cors"] = cors
    sys.modules["fastapi.responses"] = _StubModule("fastapi.responses")

    for name in ("httpx", "libtorrent", "bs4", "pydantic", "cryptography", "cryptography.fernet"):
        sys.modules[name] = _StubModule(name)


def load_structure_helper():
    sys.path.insert(0, str(BACKEND / "tests"))
    import app_structure  # noqa: WPS433

    return app_structure.extract


def structure_for(module_name: str) -> dict:
    os.environ.setdefault("CACHE_ONLY_MODE", "true")
    os.environ.setdefault("SEEDR_SESSION_SECRET", "stub-secret")
    install_stubs()
    sys.path.insert(0, str(BACKEND))
    extract = load_structure_helper()
    module = __import__(module_name)
    return extract(module.app)


def full_snapshot() -> dict:
    # Each structure needs a fresh interpreter state because fullstack_app edits main.app.
    import subprocess

    result = {}
    for module_name in ("main", "fullstack_app"):
        proc = subprocess.run(
            [sys.executable, "-I", str(Path(__file__).resolve()), "--one", module_name],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        if proc.returncode != 0:
            sys.stderr.write(proc.stdout + proc.stderr)
            raise SystemExit(f"stub import of {module_name} failed")
        result[module_name] = json.loads(proc.stdout)
    return result


def main(argv: list[str]) -> int:
    if len(argv) >= 3 and argv[1] == "--one":
        print(json.dumps(structure_for(argv[2])))
        return 0
    snapshot = full_snapshot()
    text = json.dumps(snapshot, indent=1, sort_keys=False) + "\n"
    if "--write" in argv:
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(text)
        print("wrote", SNAPSHOT.relative_to(ROOT))
        return 0
    if "--check" in argv:
        expected = json.loads(SNAPSHOT.read_text())
        if expected == snapshot:
            print("structure matches snapshot:", {k: len(v["routes"]) for k, v in snapshot.items()}, "routes")
            return 0
        for key in snapshot:
            if expected.get(key) != snapshot[key]:
                _diff(key, expected.get(key, {}), snapshot[key])
        return 1
    print(text)
    return 0


def _diff(label: str, expected: dict, actual: dict) -> None:
    print(f"MISMATCH in {label}")
    for part in ("routes", "middleware", "exception_handlers", "startup", "shutdown"):
        exp, act = expected.get(part), actual.get(part)
        if exp == act:
            continue
        print(f"  {part}: expected {len(exp or [])} items, got {len(act or [])}")
        if isinstance(exp, list) and isinstance(act, list):
            for i, (a, b) in enumerate(zip(exp, act)):
                if a != b:
                    print(f"    first difference at index {i}: expected {a} got {b}")
                    break
            else:
                print("    prefix identical; lengths differ")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
