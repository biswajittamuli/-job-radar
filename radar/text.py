import html
import re

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def strip_html(s: str | None) -> str:
    if not s:
        return ""
    # Greenhouse double-escapes its content field
    s = html.unescape(html.unescape(s))
    s = _TAG.sub(" ", s)
    return _WS.sub(" ", s).strip()
