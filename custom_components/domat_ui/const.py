"""Constants for the Domat UI integration."""

DOMAIN = "domat_ui"

CONF_HUB = "hub"
CONF_UNIT = "unit"
CONF_NAME = "name"

CONF_SCAN_INTERVAL = "scan_interval"
CONF_HEATING_OUTPUT = "heating_output"
CONF_HYSTERESIS = "hysteresis"

OUTPUT_NONE = "none"
OUTPUT_DO1 = "do1"
OUTPUT_DO2 = "do2"

DEFAULT_SCAN_INTERVAL = 15
DEFAULT_HYSTERESIS = 0.2
SCHEDULE_REFRESH_POLLS = 40  # re-read the weekly schedule every N polls

SERVICE_SET_SCHEDULE = "set_schedule"
