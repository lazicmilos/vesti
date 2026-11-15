"""Pun tekst najave sa stranice laboratorije, jer RSS laboratorija daje samo ~150 znakova."""

from datetime import datetime
from html.parser import HTMLParser

from aitracker.db import Conn
from aitracker.sources.base import PoliteClient, SourceError

# Mistral najava ima 23k znakova, a licenca i cene su na samom kraju; 40k ≈ 10k tokena.
MAX_CHARS = 40_000
# Delovi stranice koji nisu tekst najave; sadržaj unutar njih se preskače.
_SKIP = {"script", "style", "noscript", "template", "svg", "nav", "header", "footer", "aside",
         "form"}


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and (text := " ".join(data.split())):
            self.parts.append(text)


def extract_text(html: str) -> str:
    """Vidljiv tekst stranice, red po HTML čvoru; prvi red je `<title>`."""
    parser = _TextParser()
    parser.feed(html)
    return "\n".join(parser.parts)[:MAX_CHARS]


def fill_fulltext(
    conn: Conn, client: PoliteClient, source: str, source_id: int, inserted_at: datetime
) -> list[dict[str, str]]:
    """Zamenjuje RSS tekst dokumenata upisanih u `inserted_at` punim tekstom stranice.

    `content_hash` ostaje od RSS teksta, da deduplikacija ostane stabilna. Neuspelo
    preuzimanje zadržava RSS tekst i vraća grešku koja ne menja status pokretanja.
    """
    # ponytail: neuspelo preuzimanje se ne ponavlja sutra; dodati ako greške budu česte.
    rows = conn.execute(
        "SELECT id, url_canonical FROM documents WHERE source_id = %s AND fetched_at = %s",
        (source_id, inserted_at),
    ).fetchall()
    errors = []
    for doc_id, url in rows:
        try:
            text = extract_text(client.get(url).text)
        except SourceError as exc:
            errors.append({"source": source, "kind": "fulltext", "message": str(exc)})
            continue
        if text:
            conn.execute("UPDATE documents SET content = %s WHERE id = %s", (text, doc_id))
    return errors
