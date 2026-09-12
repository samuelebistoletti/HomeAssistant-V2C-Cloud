# Task Board

## Today (091226 — sabato)
- [x] **1.4.0-beta.9 rilasciata** (PR #68, squash): auto-recupero dell'indirizzo LAN dopo un cambio DHCP + slider potenza contrattuale esteso a -5 kW — 091226
- [ ] **Verificare sul vivo la beta.9 su XQUXDU**: (a) togliere l'IP manuale 10.35.0.50 dalle opzioni e controllare che `sensor.garage_xquxdu_trasporto_attivo` resti `lan` con `ip_source` = `lan`/`cloud`/`cache` invece di `manual`; (b) provare a portare lo slider **Potenza contrattuale** a un valore negativo e confermare che il Trydan lo accetti (il registro è signed e l'integrazione non impone range, ma l'accettazione lato firmware non è verificata da qui).
- [ ] **Punto 3 del documento (collisione unique_id) — IN STANDBY su richiesta utente.** Evento singolo l'11/09 18:32, ~35 righe ERROR, nessun danno: le entità esistenti sono sopravvissute. Sospetto doppio setup nello stesso reload con due schemi di unique_id (`v2c_XQUXDU_house_power` vs `XQUXDU_active_transport`). Da guardare in `async_setup_entry` / discovery multi-charger quando si riprende.
- [ ] **Promuovere 1.4.0-beta.9 → stable** dopo conferma dell'utente sui test dal vivo (device XQUXDU): IP manuale, sopravvivenza all'outage cloud, disponibilità onesta dei controlli cloud-only, auto-recupero dell'indirizzo LAN.
- [ ] **Approvare/rifiutare le 3 revisioni SOP proposte dall'auditor il 090826** (vedi sotto in Note SOP) — richiedono ok utente prima di toccare `knowledge-base.md`. **Correzione emersa dall'audit 091126: la revisione #1 come scritta è sbagliata** — dice di riscrivere come SUPERSEDED la entry `[060926]` di `knowledge-base.md`, ma quella entry non esiste nella KB: è rimasta solo una nomination, mai promossa. Va promossa direttamente con linguaggio "supersede", non riscritta.
- [ ] **Monitorare issue #54**: aggiornamento pubblicato il 091126 (nessuna risposta da V2C); ripubblicare quando V2C risponde o quando 1.4.0 diventa stable.
- [ ] **Bug trovato 091126, NON ancora fissato (segnalato dall'utente, fix rimandato apposta):** `config_flow.py::async_step_cloud` mostra la propria form con `step_id="user"` invece di `step_id="cloud"` (riga 241). Effetto visibile: il passo "Con un account V2C" mostra titolo e descrizione del menu precedente ("Come vuoi collegarti?" + il testo che spiega le due opzioni) invece di quelli propri dello step cloud ("V2C Cloud account" / "Enter the API key..."), e il campo `api_key` appare senza etichetta perché lo step "user" in strings.json non ha una sezione `data` con quella chiave — HA mostra il nome grezzo del campo. Fix: cambiare `step_id="user"` → `step_id="cloud"` alla riga 241 di `async_step_cloud`.
- [ ] **Secondo bug trovato 091126, stessa richiesta di rimando:** la translation key `cannot_connect_local` è usata in 5 punti (`_net.py::validate_private_ip` ×3, `config_flow.py::_probe_local_api` ×2) e propagata a `errors["base"]`/`errors[ATTR_IP_ADDRESS]` in **due schermate diverse** — lo step di setup "Solo locale" (riga 176) e la form "IP address for {device}" nelle opzioni (riga 479) — ma la chiave **non è mai stata definita**, in nessuna delle 4 sezioni `error` (`strings.json`, `en.json`, `it.json`, `es.json`). L'utente vede il testo grezzo `cannot_connect_local` invece di un messaggio (visto nello screenshot: IP non raggiungibile durante il setup LAN-only). Fix: aggiungere la entry mancante alle 4 sezioni `error` di `config` (serve anche in `options.error` se `_probe_local_api`/`validate_private_ip` sono richiamati anche lì — verificare). **Nota sistemica:** il test di parità traduzioni (`test_manifest_hygiene.py::TestTranslationsParity`) controlla solo che le 3 lingue combacino *tra loro*, non che ogni chiave usata nel codice Python esista in `strings.json` — per questo il buco è invisibile ai test esistenti su tutte e 4 le lingue contemporaneamente. Andrebbe aggiunto un test che estrae ogni literal passata a `errors[...]` nel codice e verifica che esista in `strings.json`.

## Note SOP in attesa di approvazione (auditor, 090826)
1. Riscrivere la entry `[060926]` di `knowledge-base.md` sul pip-audit come **SUPERSEDED**: preferire il fix di versione reale alla ignore-list quando è raggiungibile; ignore scoped solo se non esiste fix.
2. Nuova entry *Testing Gotchas*: "HTTP 200 non è prova di conformità" per ogni endpoint il cui body è stato inferito senza spec.
3. Nuova entry *Project Patterns*: la traduzione cloud→LAN di enum/unità va applicata **una sola volta** allo stesso confine di sintesi (`_build_realtime_from_reported`), citando il rischio di auto-annullamento dello swap ChargeState.

## This Week
- [ ] (se nessuna issue in arrivo) refactor dal Backlog: service dispatcher → ServiceSpec data-driven, oppure split di `_async_update_data` — rinviato di nuovo, la settimana è andata su conformità API + resilienza cloud-outage.
- [ ] Rimuovere lo shim `_install_aioresponses_compat` quando aioresponses pubblicherà una release che passa `stream_writer` da sola.
- [ ] Raccogliere feedback comunitario sulla 1.4.0 una volta stable.
- [ ] Decidere se mantenere/chiudere il canale HACS beta ora che 1.4.0 è vicina alla stable.
- [ ] Smaltire il backlog di `knowledge-nominations.md` — 34 in sospeso (060126/060926/090826/091126). Audit 091126: 9 sono duplicati esatti di entry già promosse (051926/052126) e scartabili subito; 3 si sovrappongono alle SOP in attesa sopra (non promuovere due volte); ~19 restano candidate genuine per un passaggio completo.
- [ ] Nuova SOP da proporre: "dopo ogni bump minor di ruff con `select=ALL`, girare `ruff check . --statistics` prima di toccare codice" — il pattern si è ripetuto 3 volte (D213, PLW0108, CPY001/PLR0917), soglia raggiunta per una regola formale (segnalato dall'audit 091126).

## Backlog
- [ ] Valutare se i 5 commit README (promo sconto Trydan) su main richiedono una entry CHANGELOG/release, o restano solo docs. Spostato in Backlog il 091226 dopo 3+ rinvii — bassa priorità.
- [ ] Answer Claudify tailoring questions → update memory + skills (deferred from 031826).
- [ ] Future: implement V2C cloud webhooks (startCharge/endCharge). **Sbloccato a metà (090826):** la spec OpenAPI ora documenta il payload (`idCharge`, `deviceId`, `method`, `datetime`, `energy`, `energyByHour`, `rfidCode`), ma NON c'è meccanismo di firma/auth e l'URL si registra solo dal portale V2C → payload da trattare come untrusted con validazione `deviceId`.
- [ ] ~~Migrare via da `aioresponses`~~ — non più necessario per aiohttp 3.14 (risolto con lo shim in conftest, 090826). Resta valido solo se aioresponses venisse abbandonato a monte.
- [ ] Future: refactor del service dispatcher in `__init__.py` (~640 righe ripetitive → ServiceSpec data-driven).
- [ ] Future: split di `_async_update_data` (136 righe) in 3 helper.

## Done
_(cleared 091126 — venerdì; storico completo in Daily Notes/ e git log)_

- [x] **1.4.0-beta.1 rilasciata** (PR #55, squash): schema v3, setup LAN-only senza account, override IP manuale per-charger, degrade-invece-di-teardown con repair issue, sensore diagnostico `Active transport`, 6 sensori per-fase, fix `async_shutdown` mai awaited, campo `days_of_week` — 091126
- [x] Merge 2 PR Dependabot (#56 devcontainers/node, #57 hassfest SHA) — 091126
- [x] **Bug critico trovato e fisso**: `isinstance(entry.data, dict)` scartava IP manuali e cache pairing su ogni istanza reale (HA espone `MappingProxyType`, non `dict`) pur passando 568 test con dict finti; fix con `Mapping` — beta.3, PR #60 — 091126
- [x] Commit atomico dell'options flow (merge dei delta sull'entry corrente, non su uno snapshot) — beta.3, PR #60 — 091126
- [x] UX checkbox IP manuale sistemata su più giri: label rotta, gestione cloud-only, specchio dello stato salvato, elenco indirizzi in uso, errore se nessun charger noto — PR #58/#59/#61 — 091126
- [x] **Disponibilità onesta dei controlli cloud-only** (OCPP, RFID, tipo installazione, slave, lingua, riavvio, aggiornamento firmware, sensore connessione) quando il cloud non risponde — beta.5, PR #62 — 091126
- [x] **Bug trovato e fisso**: `V2CAuthError` inghiottita da `asyncio.gather(return_exceptions=True)` a due livelli, mascherava l'outage per un'ora dopo ogni riavvio — beta.6, PR #63 — 091126
- [x] 2 rilievi Codex risolti (clear IP su entry 4G, refresh del coordinator dopo comando rifiutato, rollback dello switch su fallimento) — beta.7, PR #64 — 091126
- [x] Race su comandi sovrapposti risolta in due giri di revisione Codex (token per-comando + drop-non-restore sullo stato ottimistico) — beta.8, PR #65 — 091126
- [x] Entrambi i README riscritti per il set di feature 1.4.0 + nuova sezione "Running without the cloud" — PR #66 — 091126
- [x] Aggiornata la issue #54 con un riepilogo per gli utenti coinvolti; nessuna risposta ancora da V2C — 091126
- [x] Rimossi tutti i riferimenti all'incidente specifico (issue #54, date) da codice/commenti/test/README su richiesta dell'utente — PR #67 — 091126
- [x] Fine giornata: 0 PR aperte, 614 test verdi, main a `1.4.0-beta.8` — 091126

