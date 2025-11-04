# Integrazione V2C Cloud per Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

Questa integrazione consente di collegare Home Assistant al servizio **V2C Cloud** utilizzando la [nuova documentazione ufficiale](https://api.v2charge.com/). Dopo aver configurato l'API key del proprio account V2C viene creato un dispositivo per ogni wallbox associata, con entità che sfruttano in modo combinato le API cloud e gli endpoint **locali** esposti dalla wallbox per ridurre l’impatto sul rate limit.

> ℹ️ Il progetto è stato sviluppato da zero per V2C Cloud, prendendo come riferimento la struttura tipica delle integrazioni Home Assistant.

## ✨ Funzionalità principali

- **Autenticazione tramite API key** – la procedura guidata richiede solo la chiave generata dal portale V2C Cloud.
- **Architettura ibrida cloud/local** – i dati in tempo reale (potenza, intensità, fotovoltaico, Wi-Fi, ecc.) sono letti ogni 30 s dall’endpoint locale `http://<IP>/RealTimeData`, mentre il cloud viene contattato solo per pairing, stato generale e comandi non disponibili in LAN.
- **Aggiornamento adattivo** – il polling cloud (principalmente `/device/reported`) è raggruppato in un unico coordinator che adatta automaticamente l'intervallo in base al numero di wallbox, mantenendo un budget operativo di ~850 richieste/giorno e lasciando margine per comandi manuali.
- **Automazioni più veloci** – switch e numerici per dinamica di ricarica, blocco e intensità aggiornano immediatamente la wallbox tramite `/write/KeyWord=Value`, senza attendere il refresh cloud.
- **Comandi rapidi** – pulsanti per avviare/pausare la ricarica (locale), oltre ai comandi cloud necessari come reboot e aggiornamento firmware.
- **Servizi Home Assistant completi** – Wi-Fi, timer, tessere RFID, profili fotovoltaici v2, configurazione OCPP/Denka/inverter e raccolta statistiche con pubblicazione su eventi dedicati (`v2c_cloud_wifi_scan`, `v2c_cloud_power_profiles`, `v2c_cloud_device_statistics`, `v2c_cloud_global_statistics`).

## 🛠 Prerequisiti

- Account V2C Cloud con almeno una wallbox registrata e accesso all'API key da [https://v2c.cloud/home/user](https://v2c.cloud/home/user).
- La wallbox deve essere raggiungibile sulla LAN (l'endpoint locale risponde su `http://<IP>/RealTimeData` e `http://<IP>/write/...`).
- Home Assistant 2023.12 o successivo.
- Connettività Internet verso `https://v2c.cloud/kong/v2c_service`.

## 📦 Installazione (HACS consigliata)

1. Aggiungi questo repository a HACS in modalità "Custom repository" (categoria *Integration*).
2. Cerca **V2C Cloud** e installa l'integrazione.
3. Riavvia Home Assistant quando richiesto.
4. Vai su **Impostazioni → Dispositivi e servizi → Aggiungi integrazione**, quindi seleziona **V2C Cloud** e inserisci la tua API key.

### Installazione manuale

1. Copia la cartella `custom_components/v2c_cloud` nella directory `custom_components` della tua istanza Home Assistant.
2. Riavvia Home Assistant.
3. Aggiungi l'integrazione **V2C Cloud** dalle impostazioni.

## ⚙️ Configurazione iniziale

- L'unico dato richiesto è l'API key; opzionalmente è possibile indicare un endpoint alternativo (per ambienti di test).
- Al termine della procedura verrà creato un dispositivo per ogni pairing restituito dall'endpoint `/pairings/me`.
- Le entità vengono aggiornate con un intervallo adattivo (≥90 s) calcolato in base al numero di dispositivi collegati, così da rimanere sotto il tetto di 1000 chiamate giornaliere.

## ⏱️ Frequenza aggiornamenti e rate limiting

- Ogni ciclo di polling utilizza una sola chiamata `/device/reported` per wallbox; i pairing vengono memorizzati per 60 minuti prima di essere richiesti nuovamente.
- Le informazioni meno dinamiche (tessere RFID e versione firmware) vengono aggiornate all'avvio e poi a intervalli dilatati (6 ore per RFID, 12 ore per la versione) o quando non sono ancora state recuperate.
- Il coordinatore ridetermina automaticamente l'intervallo di aggiornamento in base al numero di dispositivi, mantenendo un budget operativo di circa 850 richieste/giorno per lasciare margine a comandi manuali (switch, servizi, pulsanti). L'intervallo minimo è 90 s, quello di default 120 s; con N wallbox viene calcolato `ceil(N * 86400 / 850)`.
- I pulsanti e gli switch che usano le API locali si aggiornano in autonomia senza attendere il ciclo cloud; se disponibile la risposta locale viene preferita per evitare oscillazioni dello stato.
- L'ultima risposta del cloud include gli header `RateLimit-*`; il loro contenuto è disponibile in `coordinator.data["rate_limit"]` per eventuali diagnostiche avanzate.

## 🔌 Entità esposte

### Sensori (aggiornati via LAN ogni 30 s)

- **Identificativo dispositivo / Firmware**.
- **Stato di ricarica** (mappato da 0 a 5), **stato di prontezza**, **timer attivo**, **caricatore bloccato**, **pausa dinamica**.
- **Potenza di ricarica**, **energia sessione**, **tempo di ricarica**, **potenza casa/FV/batteria**, **potenza contrattuale**.
- **Intensità corrente, minima e massima**, **modalità dinamica**, **modalità potenza dinamica**.
- **Tensione di installazione**, **SSID e IP Wi-Fi**, **qualità segnale**.

### Sensori binari

- **Connessione cloud** – indica se la wallbox risulta online (dati cloud).

### Switch

- **Modalità dinamica** e **blocco caricatore** – comandi locali (`/write/Dynamic`, `/write/Locked`).
- **Logo LED**, **lettore RFID**, **OCPP abilitato** – comandi cloud.

### Select

- **Tipo di installazione**, **dispositivo slave**, **lingua**, **modalità fotovoltaica** – comandi cloud.

### Number

- **Intensità corrente / minima / massima** – comandi locali (`/write/Intensity`, `/write/MinIntensity`, `/write/MaxIntensity`).
- **Potenza massima** – comando cloud (`/device/maxpower`).

### Pulsanti

- **Avvia ricarica** e **metti in pausa** – comandi locali (`/write/Paused=0/1`).
- **Riavvia dispositivo** e **richiedi aggiornamento firmware** – comandi cloud.

## 🧰 Servizi disponibili

### Configurazione e rete

| Servizio | Endpoint | Descrizione |
| --- | --- | --- |
| `v2c_cloud.set_wifi_credentials` | `/device/wifi` | Aggiorna SSID e password Wi-Fi. |
| `v2c_cloud.program_timer` | `/device/timer` | Imposta start/end time e stato attivo di un timer. |
| `v2c_cloud.set_ocpp_enabled` | `/device/ocpp` | Attiva o disattiva la funzionalità OCPP. |
| `v2c_cloud.set_ocpp_id` | `/device/ocpp_id` | Configura l'identificatore OCPP del punto di ricarica. |
| `v2c_cloud.set_ocpp_address` | `/device/ocpp_addr` | Configura l'URL del server OCPP centrale. |
| `v2c_cloud.set_denka_max_power` | `/device/denka/max_power` | Imposta la potenza massima consentita per dispositivi Denka. |
| `v2c_cloud.set_inverter_ip` | `/device/inverter_ip` | Configura l'indirizzo IP dell'inverter fotovoltaico collegato. |
| `v2c_cloud.trigger_update` | `/device/update` | Avvia la ricerca e l'installazione di aggiornamenti firmware. |

### Gestione RFID

| Servizio | Endpoint | Descrizione |
| --- | --- | --- |
| `v2c_cloud.register_rfid` | `/device/rfid` (POST) | Abilita la registrazione di una nuova tessera che verrà letta dal lettore. |
| `v2c_cloud.add_rfid_card` | `/device/rfid/tag` (POST) | Registra manualmente una tessera specificando UID e nome. |
| `v2c_cloud.update_rfid_tag` | `/device/rfid/tag` (PUT) | Aggiorna l'etichetta associata a una tessera esistente. |
| `v2c_cloud.delete_rfid` | `/device/rfid` (DELETE) | Rimuove una tessera RFID tramite codice UID. |

### Ricariche programmate

| Servizio | Endpoint | Descrizione |
| --- | --- | --- |
| `v2c_cloud.set_charge_stop_energy` | `/device/charger_until_energy` | Arresta automaticamente la ricarica al raggiungimento dei kWh indicati. |
| `v2c_cloud.set_charge_stop_minutes` | `/device/charger_until_minutes` | Arresta automaticamente la ricarica dopo il numero di minuti indicato. |
| `v2c_cloud.start_charge_for_energy` | `/device/startchargekw` | Avvia una ricarica che termina al raggiungimento dell'energia target. |
| `v2c_cloud.start_charge_for_minutes` | `/device/startchargeminutes` | Avvia una ricarica che termina dopo la durata indicata. |

### Profili di potenza FV v2

| Servizio | Endpoint | Descrizione |
| --- | --- | --- |
| `v2c_cloud.create_power_profile` | `/device/savepersonalicepower/v2` | Crea un profilo personalizzato (payload JSON). |
| `v2c_cloud.update_power_profile` | `/device/personalicepower/v2` (POST) | Aggiorna un profilo esistente. |
| `v2c_cloud.get_power_profile` | `/device/personalicepower/v2` (GET) | Recupera un profilo tramite timestamp `updateAt`. |
| `v2c_cloud.delete_power_profile` | `/device/personalicepower/v2` (DELETE) | Elimina un profilo indicandone nome e timestamp. |
| `v2c_cloud.list_power_profiles` | `/device/personalicepower/all` | Elenca tutti i profili associati al dispositivo. |

### Statistiche e diagnostica

| Servizio | Endpoint | Descrizione |
| --- | --- | --- |
| `v2c_cloud.get_device_statistics` | `/stadistic/device` | Ottiene le ultime statistiche del dispositivo (con filtri data opzionali). |
| `v2c_cloud.get_global_statistics` | `/stadistic/global/me` | Ottiene le statistiche aggregate dell'account. |
| `v2c_cloud.scan_wifi_networks` | `/device/wifilist` | Richiede una scansione Wi-Fi; i risultati sono pubblicati sull'evento `v2c_cloud_wifi_scan`. |

Gli endpoint che restituiscono dati (statistiche, profili, reti Wi-Fi) pubblicano l'esito anche sugli eventi Home Assistant `v2c_cloud_device_statistics`, `v2c_cloud_global_statistics` e `v2c_cloud_power_profiles`, facilitando l'integrazione con automazioni e notifiche.

## 📝 Log e diagnostica

Abilita il logger per `custom_components.v2c_cloud` per messaggi dettagliati:

```yaml
logger:
  logs:
    custom_components.v2c_cloud: debug
```

## 📄 Licenza

Il progetto è distribuito con licenza MIT. Consulta il file [LICENSE](LICENSE) per i dettagli.
