"""Error normalization (T2 = regex rules): strip what changes every time, keep the words."""
import re

LEVEL = re.compile(r"^\s*(ERROR|WARN|WARNING|INFO|DEBUG)\s+", re.I)
RULES = [
    (re.compile(r"\{[^}]*\}"), "<N>"),                     # f-string holes in source code
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f-]{27}\b", re.I), "<ID>"),  # UUIDs
    (re.compile(r"\b0x[0-9a-f]+\b", re.I), "<ID>"),
    (re.compile(r"\d+(\.\d+)?"), "<N>"),                   # numbers
]


def normalize_template(text: str) -> str:
    text = LEVEL.sub("", text.strip())
    for rx, rep in RULES:
        text = rx.sub(rep, text)
    return re.sub(r"\s+", " ", text)


def tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z_<>]+", normalize_template(text).lower()) if len(t) > 2}
