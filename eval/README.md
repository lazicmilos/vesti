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

Skupovi `cluster_pairs.csv` i `summaries_review.csv` i skripta `run_eval.py` dolaze u F3 i F4.
