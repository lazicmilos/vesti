# ADR-001: Statički JSON izvoz umesto API servera

Status: Prihvaćeno | Datum: 10.11.2026. | Autori: Miloš Lazić

## Kontekst

Sajt prikazuje tracker modela i dnevni feed. Podaci se menjaju jednom dnevno, kada se pipeline
izvrši. Budžet je nula za hosting (SPEC odeljak 3): nijedna komponenta ne sme da zahteva server
koji stalno radi.

## Odluka

V1 nema API server. Pipeline posle obrade izvozi statičke JSON fajlove u `web/public/data/`
(SPEC 12.1), a Next.js sajt (`output: 'export'`) ih čita. Filtriranje, sortiranje i poređenje
modela rade u pregledaču.

## Razlozi

- Podaci se menjaju jednom dnevno, pa server koji odgovara na upite ne donosi ništa.
- Statički fajlovi se besplatno hostuju na Cloudflare Pages i ne mogu da „padnu“.
- Izvoz je deterministički, pa `git diff` nad `web/public/data/` služi kao dnevnik promena.

## Posledice

- (+) Nema troška ni održavanja servera; baza sme da se uspava između pokretanja.
- (+) Sajt radi i kad je baza nedostupna.
- (−) Ceo spisak modela se učitava u pregledač; to važi dok je `models.json` reda veličine MB.
- (−) Nema pretrage arhive na serveru.
- (−) Format JSON izvoza je javni interfejs: menja se samo uz novi ADR.

## Kada se odluka preispituje

FastAPI se uvodi kad izvoz preraste nekoliko MB ili zatreba pretraga arhive.

## Razmotrene alternative

- **FastAPI + stalno uključen server:** odbačeno, traži hosting koji nije besplatan i uvodi
  tačku otkaza bez koristi za podatke koji se menjaju jednom dnevno.
- **Sajt čita bazu direktno pri build-u:** odbačeno, vezuje deploy sajta za dostupnost baze i
  gubi `git diff` nad podacima.
