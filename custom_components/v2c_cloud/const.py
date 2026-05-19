"""Constants for the V2C Cloud Home Assistant integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "v2c_cloud"

CONF_API_KEY = "api_key"
CONF_LOCAL_UPDATE_INTERVAL = "local_update_interval"

# Cloud coordinator
DEFAULT_UPDATE_INTERVAL = timedelta(seconds=120)
MIN_UPDATE_INTERVAL = timedelta(seconds=90)
TARGET_DAILY_BUDGET = 850
MAX_RATE_LIMIT_INTERVAL = timedelta(minutes=10)
RATE_LIMIT_LOW_THRESHOLD = 150  # remaining calls below this → pace proactively
RATE_LIMIT_COMMAND_RESERVE = 50  # calls reserved for commands when pacing

# Local coordinator (LAN polling)
# DEFAULT_LOCAL_INTERVAL: stored as seconds (int) for direct use in entry.options.
DEFAULT_LOCAL_INTERVAL = 30
MIN_LOCAL_INTERVAL = 5
MAX_LOCAL_INTERVAL = 300
LOCAL_INTERVAL_SOFT_WARNING = 15  # below this we surface a UI warning
LOCAL_HTTP_TIMEOUT = 10
LOCAL_MAX_RETRIES = 3
LOCAL_RETRY_BACKOFF = 1.5
LOCAL_WRITE_RETRY_DELAY = 5

# Cloud-only mode (4G Trydan, no LAN reachability)
CLOUD_ONLY_UPDATE_INTERVAL = timedelta(seconds=120)

# Power limits (kW)
MAX_POWER_MIN_KW = 1.0
MAX_POWER_MAX_KW = 22.0
INSTALLATION_VOLTAGE_MIN = 100.0
INSTALLATION_VOLTAGE_MAX = 450.0

# Select options exposed by the API
INSTALLATION_TYPES = {
    0: {"en": "Single-phase", "it": "Monofase"},
    1: {"en": "Three-phase", "it": "Trifase"},
    2: {"en": "Photovoltaic", "it": "Fotovoltaico"},
}

SLAVE_TYPES = {
    0: {"en": "Shelly", "it": "Shelly"},
    1: {"en": "V2C v2", "it": "V2C v2"},
    2: {"en": "V2C legacy", "it": "V2C legacy"},
    3: {"en": "Huawei", "it": "Huawei"},
    4: {"en": "Solax", "it": "Solax"},
    5: {"en": "Carlo Gavazzi", "it": "Carlo Gavazzi"},
    6: {"en": "Growatt", "it": "Growatt"},
    11: {"en": "MQTT", "it": "MQTT"},
}

LANGUAGES = {
    0: {"en": "English", "it": "Inglese"},
    1: {"en": "Spanish", "it": "Spagnolo"},
    2: {"en": "Portuguese", "it": "Portoghese"},
    3: {"en": "French", "it": "Francese"},
    4: {"en": "Italian", "it": "Italiano"},
    5: {"en": "German", "it": "Tedesco"},
    6: {"en": "Romanian", "it": "Rumeno"},
    7: {"en": "Dutch", "it": "Olandese"},
    8: {"en": "Danish", "it": "Danese"},
    9: {"en": "Catalan", "it": "Catalano"},
}

DYNAMIC_POWER_MODES = {
    0: {"en": "Timed power enabled", "it": "Potenza programmata attiva"},
    1: {"en": "Timed power disabled", "it": "Potenza programmata disattiva"},
    2: {"en": "Exclusive PV mode", "it": "Modalità PV esclusiva"},
    3: {"en": "Minimum power mode", "it": "Modalità potenza minima"},
    4: {"en": "Grid + PV mode", "it": "Modalità rete + PV"},
    5: {"en": "Stop mode", "it": "Modalità stop"},
}

CHARGE_STATE_LABELS = {
    0: "Disconnected",
    1: "Vehicle connected (idle)",
    2: "Charging",
    3: "Ventilation required",
    4: "Control pilot short circuit",
    5: "General fault",
}

# Locally-writeable charge mode (Trydan Modbus spec: 0=monophasic, 1=threephasic, 2=mixed)
CHARGE_MODES = {
    0: {"en": "Monophasic", "it": "Monofase", "es": "Monofásico"},
    1: {"en": "Threephasic", "it": "Trifase", "es": "Trifásico"},
    2: {"en": "Mixed", "it": "Mista", "es": "Mixta"},
}

# Photovoltaic charging mode (cloud only — POST /device/chargefvmode)
FV_MODES = {
    0: {
        "en": "PV + Minimum Power",
        "it": "PV + Potenza minima",
        "es": "PV + Potencia mínima",
    },
    1: {"en": "Exclusive PV", "it": "PV esclusivo", "es": "PV exclusivo"},
    2: {"en": "Maximum Power", "it": "Potenza massima", "es": "Potencia máxima"},
}

# Service names
SERVICE_SET_WIFI = "set_wifi_credentials"
SERVICE_PROGRAM_TIMER = "program_timer"
SERVICE_REGISTER_RFID = "register_rfid"
SERVICE_ADD_RFID_CARD = "add_rfid_card"
SERVICE_SET_INSTALLATION_VOLTAGE = "set_installation_voltage"
SERVICE_UPDATE_RFID_TAG = "update_rfid_tag"
SERVICE_DELETE_RFID = "delete_rfid"
SERVICE_TRIGGER_UPDATE = "trigger_update"
SERVICE_SET_STOP_CHARGE_KWH = "set_charge_stop_energy"
SERVICE_SET_STOP_CHARGE_MINUTES = "set_charge_stop_minutes"
SERVICE_START_CHARGE_KWH = "start_charge_for_energy"
SERVICE_START_CHARGE_MINUTES = "start_charge_for_minutes"
SERVICE_SET_OCPP_ENABLED = "set_ocpp_enabled"
SERVICE_SET_OCPP_ID = "set_ocpp_id"
SERVICE_SET_OCPP_ADDRESS = "set_ocpp_address"
SERVICE_SET_INVERTER_IP = "set_inverter_ip"
SERVICE_SCAN_WIFI = "scan_wifi_networks"
SERVICE_CREATE_POWER_PROFILE = "create_power_profile"
SERVICE_UPDATE_POWER_PROFILE = "update_power_profile"
SERVICE_GET_POWER_PROFILE = "get_power_profile"
SERVICE_DELETE_POWER_PROFILE = "delete_power_profile"
SERVICE_LIST_POWER_PROFILES = "list_power_profiles"
SERVICE_GET_DEVICE_STATISTICS = "get_device_statistics"
SERVICE_GET_GLOBAL_STATISTICS = "get_global_statistics"
# New services added in 1.3.0 (cloud endpoints + smart router)
SERVICE_START_CHARGE = "start_charge"
SERVICE_PAUSE_CHARGE = "pause_charge"
SERVICE_SET_CHARGE_INTENSITY = "set_charge_intensity"
SERVICE_SET_LOCKED = "set_locked"
SERVICE_SET_DYNAMIC = "set_dynamic"
SERVICE_SET_FV_MODE = "set_fv_mode"
SERVICE_SET_MAX_CAR_INTENSITY = "set_max_car_intensity"
SERVICE_SET_MIN_CAR_INTENSITY = "set_min_car_intensity"
SERVICE_SET_DENKA_MAX_POWER = "set_denka_max_power"
SERVICE_GET_CONNECTED_STATUS = "get_connected_status"

# Common attribute keys
ATTR_DEVICE_ID = "device_id"
ATTR_TIMER_ID = "timer_id"
ATTR_TIME_START = "start_time"
ATTR_TIME_END = "end_time"
ATTR_TIMER_ACTIVE = "active"
ATTR_WIFI_SSID = "ssid"
ATTR_WIFI_PASSWORD = "password"  # noqa: S105
ATTR_RFID_CODE = "code"
ATTR_RFID_TAG = "tag"
ATTR_KWH = "kwh"
ATTR_MINUTES = "minutes"
ATTR_VOLTAGE = "voltage"
ATTR_ENABLED = "enabled"
ATTR_OCPP_ID = "ocpp_id"
ATTR_OCPP_URL = "ocpp_url"
ATTR_IP_ADDRESS = "ip_address"
ATTR_PROFILE_NAME = "name"
ATTR_PROFILE_PAYLOAD = "profile"
ATTR_PROFILE_TIMESTAMP = "timestamp"
ATTR_UPDATED_AT = "updated_at"
ATTR_DATE_START = "date_start"
ATTR_DATE_END = "date_end"
# New attribute keys for services added in 1.3.0
ATTR_AMPS = "amps"
ATTR_WATTS = "watts"
ATTR_LOCKED = "locked"
ATTR_FV_MODE = "mode"

# Charge intensity bounds (per Trydan spec)
INTENSITY_MIN = 6
INTENSITY_MAX = 32
DENKA_POWER_MIN = 1000
DENKA_POWER_MAX = 22000

# Event names fired after data retrieval services
EVENT_WIFI_SCAN = f"{DOMAIN}_wifi_scan"
EVENT_DEVICE_STATISTICS = f"{DOMAIN}_device_statistics"
EVENT_GLOBAL_STATISTICS = f"{DOMAIN}_global_statistics"
EVENT_POWER_PROFILES = f"{DOMAIN}_power_profiles"
EVENT_CONNECTED_STATUS = f"{DOMAIN}_connected_status"
