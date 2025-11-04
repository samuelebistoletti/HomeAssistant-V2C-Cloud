# V2C Cloud Integration – Technical Notes

## 1. Architecture Overview

### Components
- **Cloud REST client** (`custom_components/v2c_cloud/v2c_cloud.py`) incapsula tutti gli endpoint documentati su `https://v2c.cloud/kong/v2c_service`. Converte risposte testuali, gestisce retry, rate limit e caching di pairing/RFID/versione.
- **Local API helper** (`custom_components/v2c_cloud/local_api.py`) fornisce utilità per determinare l'IP statico, interrogare `http://<IP>/RealTimeData`, emettere comandi `http://<IP>/write/KeyWord=Value` e gestire eccezioni dedicate (`V2CLocalApiError`).
- **Config flow** raccoglie API key e base URL opzionale, valida l'accesso tramite `/pairings/me` e salva una unique-id deterministica.
- **Coordinatore cloud** (`DataUpdateCoordinator`) esegue polling di pairings/status con un intervallo adattivo (≥90 s) calcolato per mantenere ~850 chiamate/giorno, lasciando margine per comandi manuali (limite V2C: 1000/die).
- **Coordinatori locali** vengono creati lazy per ciascun device e interrogano `/RealTimeData` ogni 30 s. Sensori, switch e number condividono i dati locali per evitare richieste duplicate.
- **Piattaforme** (binary_sensor, sensor, switch, number, select, button) ereditano da `V2CEntity`, che espone helper per pairing, reported payload e conversioni. Le entità scelgono automaticamente il dato locale quando presente.
- **Servizi** Home Assistant sono registrati una sola volta; quelli che mutano configurazioni cloud usano il client REST, quelli che operano sulla LAN sfruttano `async_write_keyword` o i dati del coordinatore locale.

### Data Flow
```
Config Flow ──► V2CClient (cloud)
                      │
                      └──► Cloud Coordinator ──► Entities / Services / Diagnostics
                                │
                                └──► Local Coordinator(s) ──► Sensors & fast controls
```

## 2. Coordinator Data Model

```python
coordinator.data = {
    "pairings": [...],                     # risposta da /pairings/me (cache 60 min)
    "devices": {
        device_id: {
            "pairing": {...},
            "connected": bool | None,
            "current_state": Any,
            "reported": dict | None,
            "reported_raw": Any,
            "rfid_cards": list | None,
            "version": str | None,
            "additional": {
                "reported_lower": dict,
                "reported_timestamp": float,
                "rfid_cards_raw": Any,
                "_rfid_last_success": float,
                "_rfid_next_refresh": float,
                "_version_next_refresh": float,
                "version_info": dict | None,
                "static_ip": str | None,      # IP usato per la local API
            },
        },
    },
    "rate_limit": {"limit": int | None, "remaining": int | None, "reset": int | None},
}
```

I coordinatori locali memorizzano direttamente l'ultima risposta `RealTimeData` con un campo `_static_ip` di servizio.

## 3. API Coverage

### Cloud
- **Stato / pairing**: `/pairings/me`, `/device/reported`, `/device/connected`, `/device/wifilist`, `/version`.
- **Controlli**: `/device/charger_until_*`, `/device/startchargekw`, `/device/startchargeminutes`, `/device/reboot`, `/device/update`.
- **Configurazione**: `/device/logo_led`, `/device/set_rfid`, `/device/ocpp`, `/device/maxpower`, `/device/chargefvmode`, `/device/inst_type`, `/device/slave_type`, `/device/language`, `/device/denka/max_power`, `/device/ocpp_id`, `/device/ocpp_addr`, `/device/wifi`, `/device/inverter_ip`.
- **RFID**: `/device/rfid` (GET/POST/DELETE) e `/device/rfid/tag` (POST/PUT).
- **Profili FV v2**: `/device/savepersonalicepower/v2`, `/device/personalicepower/v2` (POST/GET/DELETE), `/device/personalicepower/all`.
- **Statistiche**: `/stadistic/device`, `/stadistic/global/me`.

I parametri numerici vengono inviati come stringhe per allinearsi con la documentazione ufficiale; tutte le risposte vengono normalizzate a bool/float/int/dict quando possibile.

### Locale
- **Realtime**: `GET http://<IP>/RealTimeData` (dizionario con potenze, stati, Wi-Fi, intensità, ecc.).
- **Scritture**: `GET http://<IP>/write/KeyWord=Value` utilizzato per `Dynamic`, `Locked`, `Intensity`, `MinIntensity`, `MaxIntensity`, `Paused`. Ulteriori keyword possono essere aggiunte riutilizzando gli helper.

Se la local API fallisce viene sollevato `V2CLocalApiError` e l'entità mantiene il valore precedente.

## 4. Entity Design Guidelines

- Il mixin `V2CEntity` fornisce `device_state`, `pairing`, `reported`, `reported_lower` e `get_reported_value`. Accetta un flag `refresh` opzionale in `_async_call_and_refresh` per evitare refresh cloud dopo comandi locali.
- **Sensori** usano i coordinatori locali; quelli cloud (es. connettività) leggono dal dizionario principale. Le conversioni `_as_*` garantiscono tipi numerici coerenti.
- **Switch/Number locali** applicano un lock ottimistico di 20 s dopo il comando e leggono immediatamente dalla risposta LAN, riducendo l'oscillazione tra `on`/`off`.
- **Switch/Select cloud** si appoggiano al client REST e attendono il refresh per confermare lo stato.
- **Buttons** locali (start/pause) non triggerano il refresh del coordinatore cloud; i pulsanti cloud (reboot/update) invece sì.

## 5. Services

I servizi sono registrati una sola volta al bootstrap (`_async_register_services`). Mutazioni cloud vengono avvolte da `_execute_and_refresh` che esegue il comando REST e, in caso di successo, chiede il refresh del coordinator principale. I servizi dati pubblicano sempre un evento con il payload originale (`wifi_scan`, `device_statistics`, `global_statistics`, `power_profiles`).

## 6. Error Handling

- `V2CAuthError` ⇒ avvia i flussi di re-autenticazione Home Assistant.
- `V2CRequestError` e `V2CRateLimitError` circoscrivono problemi HTTP/timeout e mantengono i dati precedenti quando possibile.
- `V2CLocalApiError` incapsula errori LAN e viene propagato come `HomeAssistantError` così da notificare l'utente senza interrompere il loop.
- Il coordinatore cloud applica un backoff esponenziale (max 3 tentativi) su timeout / 429; se fallisce, conserva la cache precedente.

## 7. Development Checklist

- Aggiornare `strings.json` e le traduzioni per ogni nuova entità/servizio.
- Documentare le modifiche in `README.md`, `TECHNICAL_NOTES.md` e `CHANGELOG.md`.
- Rivalutare l'intervallo del coordinatore se vengono introdotte nuove chiamate cloud ricorrenti.
- Validare le keyword locali aggiuntive confrontandosi con la documentazione V2C.
- Mantenere i log chiari (livello `debug`) per richieste cloud e locali.

## 8. Testing Recommendations

1. **Validazione API key** – verificare workflow di onboarding e re-auth.
2. **Rilevamento dispositivi** – testare più wallbox e valutare l'intervallo calcolato (`coordinator.update_interval`).
3. **Comandi locali** – start/pause charge, switch dinamica/blocco, intenzità min/max.
4. **Comandi cloud** – logo LED, OCPP, reboot/update, timer, RFID servizi.
5. **Fallback** – simulare indisponibilità locale e assicurarsi che l'entità ripieghi sul valore cloud senza errori non gestiti.
6. **Statistiche** – invocare `get_device_statistics` / `get_global_statistics` e verificare gli eventi generati.
