import pytest

from aitracker.db import Conn
from aitracker.dedup import insert_new, to_document, update_hn_points
from aitracker.sources.base import RawItem


def _item(url: str = "https://example.com/a", title: str = "Naslov", content: str = "Tekst",
          hn_points: int | None = None) -> RawItem:
    return RawItem(url=url, title=title, content=content, hn_points=hn_points)


def _source_id(conn: Conn) -> int:
    row = conn.execute(
        "INSERT INTO sources (name, kind, role, url) VALUES ('t', 'rss', 'news', 'u') RETURNING id"
    ).fetchone()
    assert row is not None
    return int(row[0])


def _doc_count(conn: Conn) -> int:
    row = conn.execute("SELECT count(*) FROM documents").fetchone()
    assert row is not None
    return int(row[0])


def test_to_document_kanonizuje_url_i_racuna_hash() -> None:
    doc = to_document(_item(url="https://WWW.example.com/a/?utm_source=x"))

    assert doc is not None
    assert doc.url_canonical == "https://example.com/a"
    assert len(doc.content_hash) == 64


def test_to_document_isti_opis_razlicit_naslov_daje_razlicit_hash() -> None:
    first, second = to_document(_item(title="A", content="")), to_document(_item(title="B",
                                                                                  content=""))

    assert first is not None and second is not None
    assert first.content_hash != second.content_hash


def test_to_document_neispravan_url_vraca_none() -> None:
    assert to_document(_item(url="nije-url")) is None


@pytest.mark.db
def test_insert_new_novi_dokument_se_upisuje(conn: Conn) -> None:
    inserted = insert_new(conn, _source_id(conn), [_item()])

    assert inserted == 1


@pytest.mark.db
def test_insert_new_isti_kanonski_url_se_preskace(conn: Conn) -> None:
    source_id = _source_id(conn)
    insert_new(conn, source_id, [_item(content="prva verzija")])

    inserted = insert_new(
        conn, source_id, [_item(url="https://www.example.com/a/?utm_source=rss", content="druga")]
    )

    assert inserted == 0
    assert _doc_count(conn) == 1


@pytest.mark.db
def test_insert_new_isti_hash_sadrzaja_na_drugom_urlu_se_preskace(conn: Conn) -> None:
    source_id = _source_id(conn)
    insert_new(conn, source_id, [_item(url="https://example.com/a")])

    inserted = insert_new(conn, source_id, [_item(url="https://example.com/b")])

    assert inserted == 0
    assert _doc_count(conn) == 1


@pytest.mark.db
def test_insert_new_duplikat_unutar_iste_serije_se_upisuje_jednom(conn: Conn) -> None:
    inserted = insert_new(conn, _source_id(conn), [_item(), _item()])

    assert inserted == 1


@pytest.mark.db
def test_insert_new_neispravan_url_ne_prekida_ostale(conn: Conn) -> None:
    inserted = insert_new(conn, _source_id(conn), [_item(url="nije-url"), _item()])

    assert inserted == 1


@pytest.mark.db
def test_update_hn_points_poklopljen_url_dobija_poene(conn: Conn) -> None:
    insert_new(conn, _source_id(conn), [_item()])

    updated = update_hn_points(conn, [_item(url="https://www.example.com/a/", hn_points=120)])

    row = conn.execute("SELECT hn_points FROM documents").fetchone()
    assert updated == 1
    assert row == (120,)


@pytest.mark.db
def test_update_hn_points_manji_broj_ne_smanjuje_postojece_poene(conn: Conn) -> None:
    insert_new(conn, _source_id(conn), [_item()])
    update_hn_points(conn, [_item(hn_points=120)])

    update_hn_points(conn, [_item(hn_points=80)])

    assert conn.execute("SELECT hn_points FROM documents").fetchone() == (120,)


@pytest.mark.db
def test_update_hn_points_nepoznat_url_ne_pravi_dokument(conn: Conn) -> None:
    updated = update_hn_points(conn, [_item(hn_points=50)])

    assert updated == 0
    assert _doc_count(conn) == 0
