import html
import re

_TAG = re.compile(r"<[^>]+>")
_NOISE = re.compile(r"<(script|style|noscript)\b.*?</\1\s*>", re.I | re.S)
_WS = re.compile(r"\s+")


def strip_html(s: str | None) -> str:
    if not s:
        return ""
    # Greenhouse double-escapes its content field
    s = html.unescape(html.unescape(s))
    s = _NOISE.sub(" ", s)
    s = _TAG.sub(" ", s)
    return _WS.sub(" ", s).strip()
