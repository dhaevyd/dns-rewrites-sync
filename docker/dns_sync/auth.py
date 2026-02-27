"""Session-based auth helpers"""

import bcrypt
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def is_authenticated(request: Request) -> bool:
    return request.session.get("authenticated") is True


def login_required(request: Request):
    """Return a redirect if not authenticated, else None.

    HTMX requests get an HX-Redirect header so the full page navigates
    to /login rather than swapping in the login form into a partial target.
    """
    if is_authenticated(request):
        return None
    if request.headers.get("HX-Request"):
        resp = Response(status_code=204)
        resp.headers["HX-Redirect"] = "/login"
        return resp
    return RedirectResponse("/login", status_code=303)
