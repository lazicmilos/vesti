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

## Blind test LLM-a (kapija F3)

Isti 30 dokumenata iz baze ide kroz 2–3 kandidata preko prompta `event_summary_v1`. Uzorak je
ponovljiv (fiksni seed): do 15 najava laboratorija (`openai-blog`, `deepmind-blog`,
`mistral-blog`), ostatak iz vesti. Ako jedne grupe nema dovoljno, dopunjuje je druga.

```bash
cd pipeline && uv run --env-file ../.env python ../eval/blind_test.py
```

Podrazumevani kandidati: `anthropic/claude-haiku-5.5`, `openai/gpt-6-luna`,
`deepseek/deepseek-v4.1-flash`. Drugi se zadaju sa `--models a,b,c`. Trošak ide u novi red
tabele `runs`, pa ulazi u mesečni budžet. Pre punog testa pokreni probu na nekoliko dokumenata:

```bash
uv run --env-file ../.env python ../eval/blind_test.py --docs 3
```

Ograde troška:

- `--max-usd` (podrazumevano 0,50 USD): sopstvena granica testa, proverava se između dokumenata.
- Kandidat koji padne 3 puta zaredom se izbacuje; njegovi ostali redovi imaju grešku `izbačen`.
- Prekoračen mesečni budžet prekida test. U CSV ulaze samo dokumenti koje su obradili svi
  kandidati, a ako nijedan nije obrađen, fajlovi se ne pišu.
- Prekid (Ctrl-C) ili neočekivana greška zatvara red u `runs` sa statusom `failed`.

Skripta piše dva fajla i odbija da pregazi postojeće:

- `blind_test.csv`: po tri reda za svaki dokument, oznake `A`, `B`, `C`. Mapiranje oznaka na
  modele je nasumično **za svaki dokument posebno** (pravi slučajni brojevi, ne seed uzorka),
  pa isto slovo ne znači isti model, a ponovljeno pokretanje daje drugi ključ.
  `source_text` je tačno tekst koji je model dobio: tvrdnje se proveravaju prema njemu, ne
  prema članku na linku. Neuspeo poziv ima prazan izlaz i ime greške u koloni `error`.
- `blind_test_key.json`: mapiranje i, po modelu, broj uspešnih i neuspelih poziva i trošak.
  **Ne otvaraj ga pre nego što oceniš sve redove.** Iste brojke skripta ispisuje na kraju, ali
  one ne otkrivaju koje slovo pripada kom modelu.

Oba fajla su u `.gitignore`: CSV sadrži pun tekst članaka, a on se nikad ne objavljuje
(NFR-L-001). U repo i README ide samo zbirna tabela po modelu: udeo vernih sažetaka, prosečna
ocena srpskog, broj neuspelih poziva i trošak.

| Kolona | Ko popunjava | Značenje |
| --- | --- | --- |
| `unsupported_claim` | vlasnik | `da` ako sažetak ili naslov tvrdi nešto čega nema u `source_text`; inače `ne` |
| `serbian_quality` | vlasnik | ocena srpskog 1–5 |
| `notes` | vlasnik | slobodan tekst |

Napomene za tumačenje rezultata:

- `anthropic/claude-haiku-5.5` i `openai/gpt-6-luna` ne podržavaju `temperature` (prema
  `supported_parameters` OpenRouter-a), pa se kod njih ponovljivost oslanja samo na keš.
- Klijent šalje `reasoning.effort=none`. Kandidat koji to ne podržava pokazaće se kroz
  greške (`LLMError`) ili odsečen izlaz u koloni `error`.

Skupovi `cluster_pairs.csv` i `summaries_review.csv` i skripta `run_eval.py` dolaze u F3 i F4.
