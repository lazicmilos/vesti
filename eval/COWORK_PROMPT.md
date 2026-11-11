# Uputstvo za asistenta: kandidati za `models_gold_evidence.csv`

Ovaj tekst se daje asistentu (npr. Claude Cowork) zajedno sa fajlom
`eval/models_gold_evidence.csv`. Asistent **predlaže** vrednosti sa dokazom; u zlatni skup ulaze
tek kad ih vlasnik proveri (SPEC 0.6).

---

Popunjavaš kolone `value`, `official_url` i `quote` u priloženom CSV fajlu. Svaki red je jedno
polje jednog modela. Ovaj fajl je zlatni skup za evaluaciju: meri koliko često drugi sistem
izmišlja vrednosti. Prazno polje je ispravan i vredan odgovor. Izmišljena ili zapamćena vrednost
kvari celu evaluaciju.

## Pravila

1. **Samo zvanični izvori laboratorije koja je napravila model:** njen sajt, blog najava,
   dokumentacija, stranica cena ili Hugging Face repo pod njenim nalogom. Nikad OpenRouter,
   Wikipedija, novinski članci, agregatori ni tabele poređenja.
2. **Bez znanja iz memorije.** Svaka vrednost mora imati `official_url` i u `quote` **doslovan
   citat** sa te stranice (do 200 znakova), iz kog se vrednost vidi. Ako ne nađeš citat, `value`,
   `official_url` i `quote` ostaju prazni.
3. **Ne izvodi i ne procenjuj.** Ako stranica kaže „7B“, upiši `7`. Ako ne kaže broj parametara,
   ostavi prazno, čak i kad „svi znaju“ koliko je. Dozvoljena je samo promena jedinice (npr. cena
   za 1K tokena puta 1000); tada to napiši na kraju citata u zagradi.
4. **Kolonu `owner_check` ne diraš.** Nju popunjava vlasnik.
5. Ne menjaj kolone `slug`, `name` i `field`, redosled redova ni zaglavlje.

## Format vrednosti

| `field` | Format | Primer |
| --- | --- | --- |
| `org` | ime laboratorije koja je napravila model | `Mistral AI` |
| `released_at` | datum zvanične najave, `YYYY-MM-DD` | `2025-03-24` |
| `params_b` | parametri u milijardama, tačka za decimale | `7.6` |
| `context_window` | tokeni, ceo broj; „128K“ se piše `128000` | `128000` |
| `price_in`, `price_out` | cena laboratorije u USD za 1M tokena | `0.25` |
| `license` | malim slovima, SPDX oznaka gde postoji, inače `proprietary` | `apache-2.0` |
| `open_weights` | `true` ako se težine mogu preuzeti, inače `false` | `true` |

Ako je nešto dvosmisleno (više cena po nivoima, različiti datumi), ostavi prazno i u `quote`
napiši kratko zašto, bez vrednosti.
