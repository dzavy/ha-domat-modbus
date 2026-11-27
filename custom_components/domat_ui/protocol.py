"""Register map and pure helpers for Domat UIxxx room units (FW >= 200).

Register number == Modbus protocol address. No Home Assistant imports here.
"""

from __future__ import annotations

# --- registers -------------------------------------------------------------
REG_MODULE_ID = 1
REG_FIRMWARE = 2
REG_STATUS = 3  # LSB bit0 = EEPROM write enable, MSB bit4 = knob edit in progress
REG_RELAY = 7  # LSB bit0 DO1, bit1 DO2; MSB = latch enable
REG_PROGRAM_OUT = 8  # LSB 1 = day, 2 = night, 4 = off
REG_INPUTS = 10  # LSB bit0 DI1, bit1 DI2, bit2 PUSH
REG_SET_TEMP = 11
REG_DAY_TEMP = 12
REG_NIGHT_TEMP = 13
REG_ACTUAL_TEMP = 17
REG_ACTUAL_RH = 19
REG_MODE = 20  # LSB presence mode, MSB day/night mode
REG_SETTINGS = 23  # bits 2-3 schedule type
REG_MIN_TEMP = 27
REG_MAX_TEMP = 28
REG_SCHEDULE = 101  # 7 days x 6 events x (time, value) = 84 regs

POLL_START = 1
POLL_COUNT = 28  # registers 1..28 in one request (max 50)

STATUS_EEPROM_WRITE = 0x0001
STATUS_EDIT_MODE = 0x1000

# day/night mode bits (MSB of reg 20)
DN_DAY_AUTO = 0x01
DN_NIGHT_AUTO = 0x02
DN_DAY = 0x04
DN_NIGHT = 0x08
DN_OFF = 0x10
DN_AUTO = 0x20
DN_HOLIDAY = 0x40

SCHEDULE_TYPE_DAY_NIGHT = 2

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
EVENTS_PER_DAY = 6
EVENT_DISABLED = 0x8000
SCHEDULE_VALUES = {"day": 0, "comfort": 0, "night": 1, "eco": 1, "standby": 1, "off": 2}
SCHEDULE_NAMES = {0: "day", 1: "night", 2: "off"}

MODE_DAY = "day"
MODE_NIGHT = "night"
MODE_OFF = "off"

MODULE_TYPES = {
    0x0200: "UI010", 0x0201: "UI011", 0x0202: "UI012", 0x0220: "UI020",
    0x0251: "UI051", 0x0252: "UI052", 0x0255: "UI055",
    0x0271: "UI071", 0x0272: "UI072", 0x0275: "UI075",
    0x0296: "UI900", 0x0297: "UI901", 0x0298: "UI903", 0x0299: "UI905", 0x029A: "UI907",
    0x0203: "UI300", 0x0204: "UI300/DK", 0x0205: "UI309", 0x0206: "UI309/DK",
    0x0900: "UI010BL", 0x0901: "UI011BL", 0x0902: "UI012BL", 0x0920: "UI020BL",
    0x0951: "UI051BL", 0x0952: "UI052BL", 0x0955: "UI055BL",
    0x0997: "UI901BL", 0x0998: "UI903BL", 0x0999: "UI905BL",
    0x0903: "UI300BL", 0x0905: "UI309BL",
}


def s16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def to_temp(value: int) -> float:
    return s16(value) / 100


def from_temp(value: float) -> int:
    return int(round(value * 100)) & 0xFFFF


def module_name(module_id: int) -> str:
    return MODULE_TYPES.get(module_id, f"UI (0x{module_id:04X})")


def is_domat_module(module_id: int) -> bool:
    return (module_id >> 8) in (0x02, 0x09)


def daynight_bits(regs: dict[int, int]) -> int:
    return (regs[REG_MODE] >> 8) & 0x7F


def mode_register_value(regs: dict[int, int], bits: int) -> int:
    """New value of reg 20 with the day/night byte replaced, presence byte kept."""
    return (regs[REG_MODE] & 0x007F) | (bits << 8)


def effective_mode(regs: dict[int, int]) -> str:
    """What the room should be doing right now: day, night or off."""
    dn = daynight_bits(regs)
    out = regs[REG_PROGRAM_OUT] & 0xFF
    if dn & DN_OFF:
        return MODE_OFF
    if dn & DN_DAY:
        return MODE_DAY
    if dn & DN_NIGHT:
        return MODE_NIGHT
    # auto / holiday: follow the time programme output
    if out & 0x04:
        return MODE_OFF
    if out & 0x02:
        return MODE_NIGHT
    if out & 0x01:
        return MODE_DAY
    if dn & (DN_NIGHT_AUTO | DN_HOLIDAY):
        return MODE_NIGHT
    return MODE_DAY


def schedule_type(regs: dict[int, int]) -> int:
    return (regs[REG_SETTINGS] >> 2) & 0x03


def settings_with_daynight_schedule(regs: dict[int, int]) -> int:
    return (regs[REG_SETTINGS] & ~0x000C & 0xFFFF) | (SCHEDULE_TYPE_DAY_NIGHT << 2)


def decode_schedule(raw: list[int]) -> dict[str, list[tuple[int, int]]]:
    """84 registers -> {day: [(minutes, value), ...]} with disabled events dropped."""
    result: dict[str, list[tuple[int, int]]] = {}
    for d, day in enumerate(DAYS):
        block = raw[d * 12 : d * 12 + 12]
        result[day] = [
            (block[2 * i], block[2 * i + 1])
            for i in range(EVENTS_PER_DAY)
            if not block[2 * i + 1] & EVENT_DISABLED
        ]
    return result


def encode_day(events: list[tuple[int, int]]) -> list[int]:
    """[(minutes, value), ...] -> 12 registers, sorted, unused slots disabled."""
    if len(events) > EVENTS_PER_DAY:
        raise ValueError(f"at most {EVENTS_PER_DAY} events per day")
    values: list[int] = []
    for minutes, value in sorted(events):
        values += [minutes, value]
    values += [0, EVENT_DISABLED] * (EVENTS_PER_DAY - len(events))
    return values


def parse_event(event: str | dict) -> tuple[int, int]:
    """'06:30 day' or {'time': '06:30', 'mode': 'day'} -> (390, 0)."""
    if isinstance(event, dict):
        time_str, mode = str(event.get("time", "")), str(event.get("mode", "day"))
    else:
        parts = str(event).split()
        if not parts:
            raise ValueError("empty event")
        time_str, mode = parts[0], parts[1] if len(parts) > 1 else "day"
    try:
        hours, minutes = (int(x) for x in time_str.split(":"))
    except ValueError as err:
        raise ValueError(f"invalid time '{time_str}', use HH:MM") from err
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        raise ValueError(f"invalid time '{time_str}'")
    mode = mode.lower()
    if mode not in SCHEDULE_VALUES:
        raise ValueError(f"invalid mode '{mode}', use day, night or off")
    return hours * 60 + minutes, SCHEDULE_VALUES[mode]


def format_event(minutes: int, value: int) -> str:
    name = SCHEDULE_NAMES.get(value, f"{value / 100:g}")
    return f"{minutes // 60:02d}:{minutes % 60:02d} {name}"


def expand_days(days: list[str]) -> list[str]:
    out: list[str] = []
    for day in days:
        day = day.lower()
        if day in ("all", "every_day"):
            out += DAYS
        elif day in ("weekdays", "workdays"):
            out += DAYS[:5]
        elif day == "weekend":
            out += DAYS[5:]
        elif day in DAYS:
            out.append(day)
        else:
            raise ValueError(f"invalid day '{day}'")
    return list(dict.fromkeys(out))
