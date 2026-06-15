"""
Connect to the EFS-A591S-KUS scale and print live measurements.

Usage:
    python connect_efsa591s_scale.py                    # scan / list devices
    python connect_efsa591s_scale.py CF:EA:01:28:86:45  # use known MAC address
    python connect_efsa591s_scale.py <MAC> --lb         # display in pounds
    python connect_efsa591s_scale.py <MAC> --height 175 --age 30 --female
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime

from bleak import BleakScanner

from etekcity_esf551_ble import EFSA591SScale, ScaleData, WeightUnit
from etekcity_esf551_ble.const import IMPEDANCE_KEY, WEIGHT_KEY

IMPEDANCE2_KEY = "impedance_100k"
UserProfile = None  # legacy CLI arg compatibility; unused by encrypted client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
_LOGGER = logging.getLogger(__name__)


SCALE_NAME_HINTS = ("Etekcity", "Smart Fitness Scale", "EFS-A591S", "Apex")
SCALE_SERVICE = "0000fff0-0000-1000-8000-00805f9b34fb"
# Etekcity Corporation's Bluetooth SIG company identifier (start of mfr data).
# Shared across Etekcity scales, so it matches "an Etekcity scale", not this
# model specifically — fine when you only have one Etekcity scale nearby.
ETEKCITY_MFR_ID = 0x06D0


def on_measurement(data: ScaleData) -> None:
    m = data.measurements
    weight_kg = m.get(WEIGHT_KEY)  # library always reports weight in kg
    imp1 = m.get(IMPEDANCE_KEY)
    imp2 = m.get(IMPEDANCE2_KEY)

    # Convert the kg value to the requested display unit.
    factor, unit_label = {
        WeightUnit.KG: (1.0, "kg"),
        WeightUnit.LB: (2.2046226, "lb"),
        WeightUnit.ST: (0.15747304, "st"),
    }.get(data.display_unit, (1.0, "kg"))

    if weight_kg:
        parts = [f"Weight: {weight_kg * factor:.2f} {unit_label}  ({weight_kg:.2f} kg)"]
    else:
        parts = ["Weight: --"]
    if imp1:
        parts.append(f"Impedance: {imp1} Ω")
    if imp2:
        parts.append(f"Impedance (100 kHz): {imp2} Ω")

    # Any computed body metrics (present only with the body-metrics wrapper).
    metric_labels = {
        "body_mass_index": "BMI",
        "body_fat_percentage": "Body fat %",
        "skeletal_muscle_percentage": "Skeletal muscle %",
        "muscle_mass": "Muscle mass (kg)",
        "body_water_percentage": "Body water %",
        "basal_metabolic_rate": "BMR (kcal)",
        "visceral_fat_value": "Visceral fat",
        "subcutaneous_fat_percentage": "Subcutaneous fat %",
        "fat_free_weight": "Fat-free weight (kg)",
    }
    for key, label in metric_labels.items():
        if key in m:
            parts.append(f"{label}: {m[key]}")

    print("\n" + "─" * 40)
    print(f"  {data.name}  [{data.address}]")
    for p in parts:
        print(f"  {p}")
    print("─" * 40)


async def scan_for_scale() -> str | None:
    """
    Scan for the scale and return its MAC address.

    Auto-matches on the advertised local name ("Etekcity Smart Fitness Scale"),
    the FFF0 service UUID, or Etekcity's manufacturer ID (0x06D0). Falls back to
    listing nearby devices if nothing matches. Wake the scale first (step on it)
    so it advertises.
    """
    print("Scanning 10 s…  (step on the scale so it advertises)")
    devices = await BleakScanner.discover(timeout=10.0, return_adv=True)

    for dev, adv in devices.values():
        name = (dev.name or "").upper()
        services = [str(s).lower() for s in adv.service_uuids]
        if (any(h.upper() in name for h in SCALE_NAME_HINTS)
                or SCALE_SERVICE in services
                or ETEKCITY_MFR_ID in adv.manufacturer_data):
            print(f"  Found: {dev.name or '?'} [{dev.address}]  "
                  f"(mfr={', '.join(f'0x{k:04x}' for k in adv.manufacturer_data) or '-'})")
            return dev.address

    # Fall back to a device list to pick from.
    print("\nCould not auto-identify the scale. Nearby BLE devices "
          "(strongest signal first):\n")
    rows = sorted(devices.values(), key=lambda da: -(da[1].rssi or -999))
    for dev, adv in rows:
        mfr = ", ".join(f"0x{k:04x}" for k in adv.manufacturer_data) or "-"
        print(f"  {dev.address}   rssi={adv.rssi:>4} dBm   "
              f"name={(dev.name or '(none)'):<26} mfr={mfr}")
    print("\nFind your scale above (likely the strongest signal when you're next "
          "to it, often with no name), then re-run with its address:\n"
          "  python connect_efsa591s_scale.py <ADDRESS> --lb")
    return None


async def main(args: argparse.Namespace) -> None:
    address = args.address

    if not address:
        address = await scan_for_scale()
        if not address:
            print(
                "Scale not found. Make sure it is powered on (step on it briefly to wake it),\n"
                "then try again or supply the MAC address as an argument."
            )
            sys.exit(1)

    unit = WeightUnit.LB if args.lb else (WeightUnit.ST if args.st else WeightUnit.KG)

    print(f"Connecting to scale at {address}…")
    print(f"Display unit: {unit.name}")
    print("Step onto the scale when ready. Press Ctrl+C to quit.\n")

    # With body metrics: pass height/age/sex to compute BMI, body fat, etc.
    from datetime import date

    from etekcity_esf551_ble import EFSA591SScaleWithBodyMetrics
    from etekcity_esf551_ble.esf551.body_metrics import Sex

    today = date.today()
    birthdate = date(today.year - args.age, today.month, today.day)
    scale = EFSA591SScaleWithBodyMetrics(
        address=address,
        notification_callback=on_measurement,
        sex=Sex.Female if args.female else Sex.Male,
        birthdate=birthdate,
        height_m=args.height / 100.0,
        display_unit=unit,
    )

    await scale.async_start()
    try:
        await asyncio.Event().wait()  # run until Ctrl+C
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await scale.async_stop()
        print("\nDisconnected.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EFS-A591S-KUS scale reader")
    parser.add_argument(
        "address", nargs="?", default="",
        help="BLE MAC address of the scale (e.g. CF:EA:01:28:86:45). "
             "If omitted, a scan is performed."
    )
    parser.add_argument("--lb", action="store_true", help="Display weight in pounds")
    parser.add_argument("--st", action="store_true", help="Display weight in stones")
    parser.add_argument("--height", type=int, default=170, metavar="CM",
                        help="Your height in cm (default: 170)")
    parser.add_argument("--age", type=int, default=30,
                        help="Your age in years (default: 30)")
    parser.add_argument("--female", action="store_true",
                        help="Set biological sex to female")
    parser.add_argument("--debug", action="store_true",
                        help="Enable verbose BLE debug logging")
    parser.add_argument("--log", action="store_true",
                        help="Capture all TX/RX packets + GATT table to a "
                             "timestamped .jsonl file for offline analysis")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger("etekcity_esf551_ble").setLevel(logging.DEBUG)
        # Keep connection/GATT events from the bleak client; silence the scanner
        # which emits a "Received <MAC>" line for every nearby advertisement.
        logging.getLogger("bleak.backends.winrt.client").setLevel(logging.DEBUG)
        logging.getLogger("bleak.backends.winrt.scanner").setLevel(logging.WARNING)

    asyncio.run(main(args))
