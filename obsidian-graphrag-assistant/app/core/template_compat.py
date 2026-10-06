"""Compatibility shim for Starlette's newer Jinja2Templates API."""
from __future__ import annotations

from fastapi.templating import Jinja2Templates


def patch_template_response_compat() -> None:
    """
    Allow the app's existing TemplateResponse(name, context, ...) call style.

    Starlette now prefers TemplateResponse(request, name, context, ...). The
    route code was written against the older shape, so this preserves behavior
    while keeping a single upgrade point.
    """
    if getattr(Jinja2Templates.TemplateResponse, "_legacy_compat", False):
        return

    original = Jinja2Templates.TemplateResponse

    def template_response(self, *args, **kwargs):
        if args and isinstance(args[0], str):
            name = args[0]
            context = args[1] if len(args) > 1 else kwargs.pop("context", None)
            if context is None or "request" not in context:
                return original(self, *args, **kwargs)
            remaining = args[2:]
            return original(self, context["request"], name, context, *remaining, **kwargs)
        return original(self, *args, **kwargs)

    template_response._legacy_compat = True
    Jinja2Templates.TemplateResponse = template_response
