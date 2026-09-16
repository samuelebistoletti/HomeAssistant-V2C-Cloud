# Task Board

## Today (091626 — mercoledì)
- [ ] **Nuovo, trovato durante l'investigazione via MCP HA**: log HA mostra un deprecation warning HA core 2026.9.2 → "custom integration 'v2c_cloud' has an update listener and should use it for scheduling a reload. This will stop working in Home Assistant 2026.12.0". Causa: `entry.add_update_listener(_async_options_updated)` in `__init__.py` convive con una chiamata manuale a `hass.config_entries.async_reload()` in `config_flow.py` (`V2COptionsFlow._apply`, per il cambio `connection_type`) — pattern doppio non più gradito da HA. Non blocca nulla ora (scompare da solo nel 2026.12.0), ma va sistemato prima. Non incluso in PR #70, fuori scope per oggi.
- [ ] **Promuovere 1.4.0 → stable** — la verifica dal vivo su XQUXDU è OK (vedi Done), manca solo il via libera per il cut stabile.
- [ ] **Monitorare issue #54 fino a chiusura**: aspettare conferma dalla community che rigenerare la API key ora funziona davvero (V2C ha dichiarato il fix delle 17:40 — vedi Done), poi chiudere l'issue.
- [x] **Punto 3 del documento (collisione unique_id) — CHIUSO, non più rilevante (decisione utente 091626).** Era in standby dall'11/09; l'utente ha deciso di non investigarlo. Non riaprire salvo richiesta esplicita.
- [x] **3 revisioni SOP del 090826 approvate dall'utente e promosse in `knowledge-base.md`** (sezioni nuove: *Dependency Management*, *Testing Gotchas (continued)*, *Project Patterns (continued)*). Le 3 nomination corrispondenti + il vecchio duplicato `[060926]` pip-audit (mai promosso, ora superseded) rimossi da `knowledge-nominations.md` — 091626
- [x] **PR #70 e #69 (dependabot ruff) mergiate (squash), 1.4.0-beta.10 rilasciata**, branch remoti e locali ormai inutili ripuliti (`fix/cloud-auth-repair-orphan-and-ui-bugs`, `fix/dhcp-address-recovery-1.4.0-beta.9` + stale tracking refs). Solo `main` resta.
- [x] **V2C ha confermato (17:40, thread issue #54) che l'instabilità API era un errore di sistema lato loro, ora risolto** — supera lo status "ancora attivo" del case V2C-36367 (15/09) citato nell'update precedente. Pubblicato un secondo commento di correzione su issue #54: chi è ancora bloccato deve solo rigenerare una nuova API key dal portale v2c.cloud e reinserirla da Riconfigura.
- [x] **Monitorare issue #54**: 3 aggiornamenti pubblicati oggi (root-cause dell'issue orfana + link a PR #70; poi la correzione con la conferma V2C delle 17:40).
- [x] **Verifica sul vivo beta.10 su XQUXDU completata e OK**: HACS aggiornato + restart, IP manuale rimosso (`ip_source` non più `manual`), slider potenza contrattuale negativo accettato, repair `cloud_auth_degraded` pulito, nuova API key rigenerata e funzionante — 091626

## This Week
- [ ] (se nessuna issue in arrivo) refactor dal Backlog: service dispatcher → ServiceSpec data-driven, oppure split di `_async_update_data` — rinviato di nuovo, la settimana è andata su conformità API + resilienza cloud-outage.
- [ ] Rimuovere lo shim `_install_aioresponses_compat` quando aioresponses pubblicherà una release che passa `stream_writer` da sola.
- [ ] Raccogliere feedback comunitario sulla 1.4.0 una volta stable.
- [ ] Decidere se mantenere/chiudere il canale HACS beta ora che 1.4.0 è vicina alla stable.
- [ ] Smaltire il backlog di `knowledge-nominations.md` — dopo la promozione delle 3 SOP e la rimozione di 4 nomination il 091626, restano ~30 in sospeso. Audit 091126: 9 sono duplicati esatti di entry già promosse (051926/052126) e scartabili subito; ~19 restano candidate genuine per un passaggio completo.
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
- [x] **1.4.0-beta.9 rilasciata** (PR #68, squash): auto-recupero dell'indirizzo LAN dopo un cambio DHCP + slider potenza contrattuale esteso a -5 kW — 091226
- [x] **Diagnosticato via MCP HA (system_health repairs + log) e fissato il repair `cloud_auth_degraded` che restava attivo per sempre dopo un reload riuscito.** Root cause: la pulizia dell'issue era condizionata a `auth_state.degraded` che passa da True a False nella STESSA istanza runtime; un reload (Reconfigure con nuova API key, o riavvio HA) ricrea `_CloudAuthState` con `degraded=False` di default, quindi quella transizione non si verifica mai anche se il ciclo successivo ha successo — l'issue di un runtime precedente resta orfana. Fix: pulizia incondizionata a ogni ciclo cloud riuscito (`ir.async_delete_issue` è no-op se non c'è nulla da cancellare). Confermato sull'istanza live XQUXDU: `binary_sensor.trydan_stato_connessione_v2c_cloud` disponibile e `cloud_auth_degraded_...` ancora "active":true nel registro nonostante l'auth fosse tornata sana. Aggiunto test di regressione in `test_init.py`. — PR #70, beta.10 — 091626
- [x] **Bug UI rimandato 091126 #1 fissato**: `async_step_cloud` usava `step_id="user"` invece di `step_id="cloud"` — PR #70 — 091626
- [x] **Bug UI rimandato 091126 #2 fissato**: `cannot_connect_local` mancava in tutte le sezioni `error` (config + options) di `strings.json`/`en`/`it`/`es` — aggiunta la entry mancante nelle 8 sezioni (4 lingue × 2 sezioni) — PR #70 — 091626
- [x] **Riformulato il messaggio di repair `cloud_auth_degraded`** rimuovendo il riferimento all'incidente specifico di settembre 2026 (violava la direttiva utente del 091126) — ora descrive il fallimento in modo generico — PR #70 — 091626
- [x] **Aggiornata issue #54** con la diagnosi del bug e link a PR #70; notato che V2C conferma (case V2C-36367) l'incidente ancora attivo lato loro al 15/09 — 091626

