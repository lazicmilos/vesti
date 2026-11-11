Iz priloženog teksta zvanične najave izvuci podatke o AI modelu „{{model_name}}“ (izvor: {{source_url}}).

Pravila:
1. Koristi isključivo priloženi tekst izvora. Bez znanja van teksta, čak i kad misliš da znaš tačnu vrednost.
2. Polje koje tekst ne navodi eksplicitno vraća `null`. Ne procenjuj, ne zaokružuj, ne izvodi. Ako tekst kaže „7B“, `params_b` je 7; ako ne navodi broj parametara, `params_b` je `null`.
3. `summary_sr` piši na srpskom, latinicom, u neutralnom informativnom tonu, bez superlativa i reklamnog jezika: jedna do dve rečenice o tome šta je model i čemu služi, samo na osnovu teksta.
4. Koristi termine iz rečnika dosledno:
{{glossary}}
5. Vrati samo JSON po šemi, bez dodatnog teksta.

Formati: `released_at` je datum zvanične najave (`YYYY-MM-DD`); cene su u USD po 1M tokena; `context_window` je broj tokena („128K“ je 128000); `license` malim slovima (SPDX oznaka gde postoji, inače `proprietary`); `open_weights` je `true` samo ako tekst kaže da se težine mogu preuzeti.

Tekst izvora:
<<<
{{text}}
>>>
