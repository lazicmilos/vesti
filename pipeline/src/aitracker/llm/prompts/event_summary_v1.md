Napiši naslov i sažetak tech događaja na osnovu priloženih tekstova izvora (svi opisuju isti događaj).

Pravila:
1. Koristi isključivo priložene tekstove izvora. Bez znanja van teksta. Ne dodaj tvrdnju koju nijedan izvor ne navodi.
2. Polje koje tekst ne podržava eksplicitno vraća `null`; u sažetku izostavi ono što izvori ne kažu. Ne procenjuj, ne zaokružuj, ne izvodi.
3. Piši na srpskom, latinicom, u neutralnom informativnom tonu, bez superlativa i reklamnog jezika. `title_sr` do 90 znakova; `summary_sr` od 2 do 4 rečenice.
4. Koristi termine iz rečnika dosledno:
{{glossary}}
5. Vrati samo JSON po šemi, bez dodatnog teksta.

`category`: `ai` (AI modeli, istraživanje, proizvodi), `hardware` (čipovi, uređaji), `big_tech` (poslovanje velikih tehnoloških kompanija), `security` (bezbednost, curenja, napadi); `null` ako nijedna ne odgovara.
`mentioned_models`: imena AI modela tačno kako se pojavljuju u tekstu; prazna lista ako ih nema.

Tekstovi izvora:
<<<
{{text}}
>>>
