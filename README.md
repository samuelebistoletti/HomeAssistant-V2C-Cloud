# Integrazione V2C Cloud per Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

Questa integrazione consente di collegare Home Assistant al servizio **V2C Cloud** utilizzando l'API pubblicata su [https://v2c.docs.apiary.io](https://v2c.docs.apiary.io). Dopo aver configurato l'API key del proprio account V2C viene creato un dispositivo per ogni wallbox associata, con sensori, comandi e servizi per gestire intensità, timer, tessere RFID e modalità fotovoltaiche.

> ℹ️ Il repository nasce come riscrittura completa di un'integrazione d'esempio, ora interamente dedicata a V2C Cloud.

## ✨ Funzionalità principali

- **Autenticazione tramite API key** – la procedura guidata richiede solo la chiave generata dal portale V2C Cloud.
- **Aggiornamento coordinato** – un `DataUpdateCoordinator` raccoglie periodicamente stato del caricatore, carte RFID registrate, versione firmware e statistiche globali.
- **Sensori dedicati** – stato di connessione, modalità di carica, intensità impostate, potenza massima, numero di tessere RFID e versione dispositivo.
- **Comandi rapidi** – pulsanti per avviare/pausare la ricarica, riavviare la wallbox o forzare un aggiornamento firmware.
- **Controlli configurazione** – switch, select e number per dinamica di ricarica, lingua, modalità FV, tipo installazione, intensità e potenza massime.
- **Servizi Home Assistant** – servizi personalizzati per programmare timer, impostare il Wi-Fi, gestire le tessere RFID e richiedere aggiornamenti.

## 🛠 Prerequisiti

- Account V2C Cloud con almeno una wallbox registrata e accesso all'API key da [https://v2c.cloud/api](https://v2c.cloud/api).
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
- Le entità vengono aggiornate ogni 30 secondi (valore predefinito).

## 🔌 Entità esposte

### Sensori

- **Stato di ricarica** (testuale, con mappatura degli stati A/B/C).
- **Intensità corrente / minima / massima** (Ampere).
- **Potenza massima** (kW).
- **Versione firmware**.
- **Indirizzo MAC**.
- **Conteggio tessere RFID** (con elenco tra gli attributi).

### Sensori binari

- **Connessione cloud** – indica se la wallbox risulta online.

### Switch

- **Modalità dinamica** (`/device/dynamic`).
- **Blocco caricatore** (`/device/locked`).
- **Logo LED** (`/device/logo_led`).
- **Lettore RFID** (`/device/set_rfid`).

### Select

- **Tipo di installazione** (`/device/inst_type`).
- **Dispositivo slave** (`/device/slave_type`).
- **Lingua** (`/device/language`).
- **Modalità fotovoltaica** (`/device/chargefvmode`).

### Number

- **Intensità corrente / minima / massima** (`/device/intensity`, `/device/min_car_int`, `/device/max_car_int`).
- **Potenza massima** (`/device/maxpower`).

### Pulsanti

- **Avvia ricarica** (`/device/startcharge`).
- **Metti in pausa** (`/device/pausecharge`).
- **Riavvia dispositivo** (`/device/reboot`).
- **Richiedi aggiornamento firmware** (`/device/update`).

## 🧰 Servizi disponibili

| Servizio | Endpoint | Descrizione |
| --- | --- | --- |
| `v2c_cloud.set_wifi_credentials` | `/device/wifi` | Aggiorna SSID e password Wi-Fi. |
| `v2c_cloud.program_timer` | `/device/timer` | Configura timer con giorni e orari. |
| `v2c_cloud.register_rfid` | `/device/rfid` (POST) | Abilita la registrazione di una nuova tessera con etichetta. |
| `v2c_cloud.update_rfid_tag` | `/device/rfid/tag` | Aggiorna l'etichetta associata a una tessera esistente. |
| `v2c_cloud.delete_rfid` | `/device/rfid` (DELETE) | Rimuove una tessera RFID tramite codice. |
| `v2c_cloud.trigger_update` | `/device/update` | Avvia la procedura di aggiornamento firmware. |

## 📝 Log e diagnostica

Abilita il logger per `custom_components.v2c_cloud` per messaggi dettagliati:

```yaml
logger:
  logs:
    custom_components.v2c_cloud: debug
```

## 📄 Licenza

Il progetto è distribuito con licenza MIT. Consulta il file [LICENSE](LICENSE) per i dettagli.
