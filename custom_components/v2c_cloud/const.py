"""Constants for the V2C Cloud Home Assistant integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "v2c_cloud"

CONF_API_KEY = "api_key"
CONF_BASE_URL = "base_url"

DEFAULT_BASE_URL = "https://v2c.cloud/kong/v2c_service"
DEFAULT_UPDATE_INTERVAL = timedelta(minutes=1)

# Select options exposed by the API
INSTALLATION_TYPES = {
    0: "Monophase",
    1: "Three-phase",
    2: "Photovoltaic",
}

SLAVE_TYPES = {
    0: "V2C",
    1: "Shelly",
    2: "Hoax",
    3: "Huawei",
}

LANGUAGES = {
    0: "English",
    1: "Spanish",
    2: "Portuguese",
}

FV_MODES = {
    0: "FV + Minimum Power",
    1: "Exclusive FV",
    2: "Maximum Power",
}

CHARGE_STATE_LABELS = {
    0: "State A",
    1: "State B",
    2: "State C",
}

SERVICE_SET_WIFI = "set_wifi_credentials"
SERVICE_PROGRAM_TIMER = "program_timer"
SERVICE_REGISTER_RFID = "register_rfid"
SERVICE_UPDATE_RFID_TAG = "update_rfid_tag"
SERVICE_DELETE_RFID = "delete_rfid"
SERVICE_TRIGGER_UPDATE = "trigger_update"

ATTR_DEVICE_ID = "device_id"
ATTR_TIMER_ID = "timer_id"
ATTR_DAYS_OF_WEEK = "days_of_week"
ATTR_TIME_START = "time_start"
ATTR_TIME_END = "time_end"
ATTR_WIFI_SSID = "ssid"
ATTR_WIFI_PASSWORD = "password"
ATTR_RFID_CODE = "code"
ATTR_RFID_TAG = "tag"
