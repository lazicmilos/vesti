import pytest

from aitracker.normalize import canonical_url, content_hash, normalize_text


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        pytest.param("https://Example.COM/a", "https://example.com/a", id="ep-host-velika-slova"),
        pytest.param("https://www.example.com/a", "https://example.com/a", id="ep-www"),
        pytest.param("https://example.com/a/", "https://example.com/a", id="ep-zavrsna-kosa-crta"),
        pytest.param("https://example.com/a#deo", "https://example.com/a", id="ep-fragment"),
        pytest.param("https://example.com/a?utm_source=x&utm_medium=y",
                     "https://example.com/a", id="ep-utm"),
        pytest.param("https://example.com/a?ref=hn&fbclid=1&gclid=2",
                     "https://example.com/a", id="ep-ref-fbclid-gclid"),
        pytest.param("https://example.com/a?b=2&a=1", "https://example.com/a?a=1&b=2",
                     id="ep-sortiranje-parametara"),
        pytest.param("https://example.com/a?p=1&utm_campaign=z", "https://example.com/a?p=1",
                     id="ep-mesani-parametri"),
        pytest.param("https://example.com/Put/Clanak", "https://example.com/Put/Clanak",
                     id="ep-putanja-cuva-velicinu-slova"),
        pytest.param("https://example.com/a?reference=1", "https://example.com/a?reference=1",
                     id="bva-ref-samo-tacno-ime"),
        pytest.param("https://example.com/a?utm=1", "https://example.com/a?utm=1",
                     id="bva-utm-bez-donje-crte-ostaje"),
        pytest.param("https://example.com/", "https://example.com", id="bva-samo-koren"),
        pytest.param("https://example.com", "https://example.com", id="bva-bez-putanje"),
        pytest.param("https://example.com:8443/a", "https://example.com:8443/a", id="ep-port"),
        pytest.param("  HTTPS://example.com/a  ", "https://example.com/a",
                     id="pogadjanje-razmaci-i-sema"),
        pytest.param("https://wwwexample.com/a", "https://wwwexample.com/a",
                     id="bva-www-bez-tacke-ostaje"),
    ],
)
def test_canonical_url_vazeci_url_vraca_kanonski_oblik(url: str, expected: str) -> None:
    assert canonical_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("", id="nevazeca-prazan"),
        pytest.param("/samo/putanja", id="nevazeca-relativan"),
        pytest.param("mailto:neko@example.com", id="nevazeca-sema"),
        pytest.param("https:///bez-hosta", id="nevazeca-bez-hosta"),
    ],
)
def test_canonical_url_nevazeci_url_baca_value_error(url: str) -> None:
    with pytest.raises(ValueError, match="nije http"):
        canonical_url(url)


def test_canonical_url_vec_kanonski_ostaje_isti() -> None:
    once = canonical_url("https://WWW.Example.com/a/?utm_source=x&b=1#f")

    assert canonical_url(once) == once


def test_normalize_text_html_i_razmaci_daje_cist_tekst() -> None:
    assert normalize_text("<p>Novi  <b>Model</b>\n&amp; cena</p>") == "novi model & cena"


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param("<p>Isti tekst</p>", "isti tekst", id="ep-html"),
        pytest.param("Isti   tekst\n", "isti tekst", id="ep-razmaci"),
        pytest.param("ISTI TEKST", "isti tekst", id="ep-velika-slova"),
    ],
)
def test_content_hash_razlika_samo_u_formatu_daje_isti_hash(first: str, second: str) -> None:
    assert content_hash(first) == content_hash(second)


def test_content_hash_razlicit_tekst_daje_razlicit_hash() -> None:
    assert content_hash("model a") != content_hash("model b")


def test_content_hash_prazan_tekst_vraca_sha256_dug_64_znaka() -> None:
    assert len(content_hash("")) == 64
