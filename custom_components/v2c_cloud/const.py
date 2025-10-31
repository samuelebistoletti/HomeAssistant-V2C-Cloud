"""Constants for the V2C Cloud Home Assistant integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "v2c_cloud"

CONF_API_KEY = "api_key"
CONF_BASE_URL = "base_url"

DEFAULT_BASE_URL = "https://v2c.cloud/kong/v2c_service"
DEFAULT_UPDATE_INTERVAL = timedelta(seconds=120)
MIN_UPDATE_INTERVAL = timedelta(seconds=90)
RATE_LIMIT_DAILY = 1000
TARGET_DAILY_BUDGET = 850

# Power limits (kW)
MAX_POWER_MIN_KW = 1.0
MAX_POWER_MAX_KW = 50.0

# Select options exposed by the API
INSTALLATION_TYPES = {
    0: "Monophase",
    1: "Three-phase",
    2: "Photovoltaic",
}

SLAVE_TYPES = {
    0: "Shelly",
    1: "V2C v2",
    2: "V2C legacy",
    3: "Huawei",
    4: "Solax",
    5: "Carlo Gavazzi",
    6: "Growatt",
}

LANGUAGES = {
    0: "English",
    1: "Spanish",
    2: "Portuguese",
    3: "French",
    4: "Italian",
    5: "German",
    6: "Dutch",
}

FV_MODES = {
    0: "PV + Minimum Power",
    1: "Exclusive PV",
    2: "Maximum Power",
}

CHARGE_STATE_LABELS = {
    0: "Disconnected",
    1: "Vehicle connected (idle)",
    2: "Charging",
    3: "Ventilation required",
    4: "Control pilot short circuit",
    5: "General fault",
}

# Service names
SERVICE_SET_WIFI = "set_wifi_credentials"
SERVICE_PROGRAM_TIMER = "program_timer"
SERVICE_REGISTER_RFID = "register_rfid"
SERVICE_ADD_RFID_CARD = "add_rfid_card"
SERVICE_UPDATE_RFID_TAG = "update_rfid_tag"
SERVICE_DELETE_RFID = "delete_rfid"
SERVICE_TRIGGER_UPDATE = "trigger_update"
SERVICE_SET_STOP_CHARGE_KWH = "set_charge_stop_energy"
SERVICE_SET_STOP_CHARGE_MINUTES = "set_charge_stop_minutes"
SERVICE_START_CHARGE_KWH = "start_charge_for_energy"
SERVICE_START_CHARGE_MINUTES = "start_charge_for_minutes"
SERVICE_SET_THIRDPARTY_MODE = "set_thirdparty_mode"
SERVICE_SET_OCPP_ENABLED = "set_ocpp_enabled"
SERVICE_SET_OCPP_ID = "set_ocpp_id"
SERVICE_SET_OCPP_ADDRESS = "set_ocpp_address"
SERVICE_SET_DENKA_MAX_POWER = "set_denka_max_power"
SERVICE_SET_INVERTER_IP = "set_inverter_ip"
SERVICE_SCAN_WIFI = "scan_wifi_networks"
SERVICE_CREATE_POWER_PROFILE = "create_power_profile"
SERVICE_UPDATE_POWER_PROFILE = "update_power_profile"
SERVICE_GET_POWER_PROFILE = "get_power_profile"
SERVICE_DELETE_POWER_PROFILE = "delete_power_profile"
SERVICE_LIST_POWER_PROFILES = "list_power_profiles"
SERVICE_GET_DEVICE_STATISTICS = "get_device_statistics"
SERVICE_GET_GLOBAL_STATISTICS = "get_global_statistics"

# Common attribute keys
ATTR_DEVICE_ID = "device_id"
ATTR_TIMER_ID = "timer_id"
ATTR_TIME_START = "start_time"
ATTR_TIME_END = "end_time"
ATTR_TIMER_ACTIVE = "active"
ATTR_WIFI_SSID = "ssid"
ATTR_WIFI_PASSWORD = "password"
ATTR_RFID_CODE = "code"
ATTR_RFID_TAG = "tag"
ATTR_KWH = "kwh"
ATTR_MINUTES = "minutes"
ATTR_KW = "kw"
ATTR_MODE = "mode"
ATTR_VALUE = "value"
ATTR_ENABLED = "enabled"
ATTR_OCPP_ID = "ocpp_id"
ATTR_OCPP_URL = "ocpp_url"
ATTR_IP_ADDRESS = "ip_address"
ATTR_PROFILE_NAME = "name"
ATTR_PROFILE_PAYLOAD = "profile"
ATTR_PROFILE_MODE = "profile_mode"
ATTR_PROFILE_TIMESTAMP = "timestamp"
ATTR_UPDATED_AT = "updated_at"
ATTR_DATE_START = "date_start"
ATTR_DATE_END = "date_end"
ATTR_WATTS = "watts"

# Event names fired after data retrieval services
EVENT_WIFI_SCAN = f"{DOMAIN}_wifi_scan"
EVENT_DEVICE_STATISTICS = f"{DOMAIN}_device_statistics"
EVENT_GLOBAL_STATISTICS = f"{DOMAIN}_global_statistics"
EVENT_POWER_PROFILES = f"{DOMAIN}_power_profiles"
