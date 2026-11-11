# Evaluacija

Skupove u ovom folderu **označava vlasnik ručno** (SPEC 0.6 i odeljak 13). Skripte prave samo
šablone sa kandidatima i računaju metrike; oznake koje bi generisao model čine evaluaciju
besmislenom.

## `models_gold.csv` (kapija F2 i F3)

50 nasumičnih modela iz trackera. Šablon pravi `make_models_gold.py`.

| Kolona | Ko popunjava | Značenje |
| --- | --- | --- |
| `slug`, `name`, `org`, `source_url` | skripta | identifikacija modela u trackeru |
| `gold_*` | vlasnik | tačna vrednost sa zvanične stranice; prazno = zvanični izvor je ne navodi |
| `duplicate_of` | vlasnik | `slug` drugog modela iz trackera ako je ovo isti model; inače prazno |
| `official_url` | vlasnik | stranica sa koje su vrednosti prepisane |
| `notes` | vlasnik | slobodan tekst |

Format vrednosti: datum `YYYY-MM-DD`; `gold_params_b` u milijardama; cene u USD po 1M tokena;
`gold_open_weights` je `true` ili `false`.

**Kapija F2:** kolona `duplicate_of` je prazna u svih 50 redova (0 duplikata).

### Provera duplikata

```bash
cd pipeline && uv run --env-file ../.env python ../eval/duplicate_candidates.py
```

Za svaki model iz uzorka skripta prikaže do 5 najsličnijih modela iz cele baze, iz svih
organizacija. Upiši broj kandidata ako je isti model, Enter ako nije, `p` da preskočiš, `q` da
sačuvaš i izađeš (nastavak sa `--start N`). Skripta upisuje samo kolonu `duplicate_of` i samo
ono što izabereš. Kandidati su pomoć, nisu odluka: ako sumnjaš, otvori oba linka.

### Zlatne vrednosti uz pomoć asistenta (SPEC 0.6, izuzetak)

Kolone `gold_*` se ne pišu ručno u `models_gold.csv`, nego idu kroz `models_gold_evidence.csv`:
jedan red je jedno polje jednog modela, sa vrednošću, zvaničnim URL-om i doslovnim citatom.

1. Asistentu (npr. Cowork) daj `models_gold_evidence.csv` i uputstvo iz `COWORK_PROMPT.md`.
   On popunjava `value`, `official_url` i `quote`.
2. Za svaki red sa vrednošću otvori `official_url`, nađi citat (Ctrl+F) i proveri da vrednost
   iz njega stvarno sledi. U `owner_check` upiši `da` ili `ne`. Ako je vrednost pogrešna,
   ispravi je i upiši `da`.
3. Prenesi potvrđene vrednosti u `models_gold.csv`:

```bash
cd pipeline && uv run python ../eval/apply_gold_evidence.py
```

Skripta proverava format i da svaka vrednost ima URL i citat, upisuje samo redove sa
`owner_check = da` i ispisuje koliko redova još čeka proveru. Prazno polje znači da zvanični
izvor ne navodi vrednost; ako asistent propusti vrednost koja postoji, evaluacija će LLM-ovu
tačnu vrednost brojati kao izmišljenu, što je greška na strogu stranu.

**Konvencije** (odluka vlasnika, 11. 11. 2026.), važe i za oznake i za ekstrakciju:

- Brojevi se pišu kako stoje na stranici: „128K“ je `128000`, „4k“ je `4000`, „1T“ je `1000`
  (milijardi). Ne pretvara se u „verovatnu“ vrednost (131072, 4096).
- Licenca bez SPDX oznake se piše imenom licence laboratorije (`llama2`, `gemma`,
  `modified-mit`), a `proprietary` samo kad stranica kaže da je zatvorena.
- MoE modeli: `params_b` je ukupan broj parametara (GLM-4.6 je `355`, ne 32 aktivnih).
- `released_at` je datum zvanične najave, ne datum dostupnosti u API-ju.
- Modeli porodice Qwen imaju organizaciju `Alibaba Cloud`.

Zašto ne može bez provere: evaluacija meri koliko LLM izmišlja. Ako zlatne vrednosti napravi
LLM bez provere, ista zapamćena greška bi se brojala kao tačna.

Skupovi `cluster_pairs.csv` i `summaries_review.csv` i skripta `run_eval.py` dolaze u F3 i F4.
