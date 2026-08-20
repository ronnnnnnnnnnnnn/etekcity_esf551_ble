# Etekcity ESF-551, ESF-24, ESF-17, ESF-18, FIT-8S, EFS-A591S & EFS-C651 BLE

This package provides a basic unofficial interface for interacting with Etekcity Smart Fitness Scales using Bluetooth Low Energy (BLE). It supports the [Etekcity ESF-551](https://etekcity.com/products/smart-fitness-scale-esf551), [Etekcity ESF-24](https://us.vesync.com/product-detail/etekcity-esf24-smart-fitness-scale-335), [Etekcity FIT-8S](https://etekcity.com/products/smart-fitness-scale-fit-8s), [Etekcity ESF-17/18](https://etekcity.com/collections/fitness-scales/products/smart-fitness-scale-esf18), [Etekcity EFS-A591S (Apex HR)](https://etekcity.com/products/hr-smart-fitness-scale) and [Etekcity EFS-C651](https://etekcity.com/collections/fitness-scales/products/cobra-dark-blue) models.

## Features

- **ESF-551**: Fully supported and stable (weight, impedance, body metrics, display unit management)
- **ESF-24**: Experimental support (weight, impedance, body metrics, unit changes)
- **ESF-17/18**: Experimental support (weight, impedance, body metrics, unit changes) — protocol-identical to the ESF-24 and handled by the same client class
- **FIT-8S**: Experimental support (weight, impedance, body metrics)
- **EFS-A591S (Apex HR)**: Experimental support (weight, impedance, heart rate, body metrics, unit changes)
- **EFS-C651**: Experimental support (weight, impedance, body metrics, unit changes)
- Easy connection and notification handling
- Body composition metrics for any impedance-capable scale, with optional athlete mode. Two calculators are provided, matching the two algorithms the app uses: `BodyMetrics` for the ESF-551, ESF-24, ESF-17, ESF-18, FIT-8S and EFS-A591S, and `BodyMetricsV2` for the EFS-C651. They share a common set of metrics, so they can be used interchangeably — see [Body metrics](#body-metrics)
- Display unit management (not supported on advertisement-based scales like FIT-8S)

## Supported Models

| Model | Status | Features |
|-------|--------|----------|
| ESF-551 | ✅ Fully Supported | Weight, impedance, body metrics, unit changes |
| EFS-A591S | 🔬 Experimental | Weight, impedance, heart rate, body metrics, unit changes |
| ESF-24 | 🔬 Experimental | Weight, impedance, body metrics, unit changes |
| ESF-17 | 🔬 Experimental | Weight, impedance, body metrics, unit changes |
| ESF-18 | 🔬 Experimental | Weight, impedance, body metrics, unit changes |
| FIT-8S | 🔬 Experimental | Weight, impedance, body metrics |
| EFS-C651 | 🔬 Experimental | Weight, impedance, body metrics, unit changes |

**Disclaimer: This is an unofficial, community-developed library. It is not affiliated with, officially maintained by or in any way officially connected with Etekcity, VeSync Co., Ltd. (the owner of the Etekcity brand) or any of their subsidiaries or affiliates. The official Etekcity website can be found at https://www.etekcity.com, and the official VeSync website at https://www.vesync.com. The names "Etekcity" and "VeSync" as well as related names, marks, emblems and images are registered trademarks of their respective owners.**

[![Buy Me A Coffee](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/ronnnnnnn)


## Installation

Requires Python 3.11+ and bleak 2.x or 3.x. Install using pip:

```bash
pip install etekcity_esf551_ble
```


## Quick Start

Here's a basic example of how to use the library:

```python
import asyncio
from etekcity_esf551_ble import (
    IMPEDANCE_KEY,
    WEIGHT_KEY,
    ESF551Scale,
    ScaleData,
    WeightUnit,
    BodyMetrics,
    Sex,
)

async def main():
    def notification_callback(data: ScaleData):
        print(f"Weight: {data.measurements[WEIGHT_KEY]} kg")
        print(f"Display Unit: {data.display_unit.name}")
        if IMPEDANCE_KEY in data.measurements:
            print(f"Impedance: {data.measurements[IMPEDANCE_KEY]} Ω")

            # Calculate body metrics (any impedance-capable scale).
            # Use BodyMetricsV2 instead for an EFS-C651 — see "Body metrics".
            # Note: Replace with your actual height, age and sex
            body_metrics = BodyMetrics(
                weight_kg=data.measurements[WEIGHT_KEY],
                height_m=1.75,
                age=30,
                sex=Sex.Male,
                impedance=data.measurements[IMPEDANCE_KEY],
                athlete=False,
            )
            print(f"Body Mass Index: {body_metrics.body_mass_index:.2f}")
            print(f"Body Fat Percentage: {body_metrics.body_fat_percentage:.1f}%")
            print(f"Fat-Free Weight: {body_metrics.fat_free_weight:.2f} kg")
            print(f"Subcutaneous Fat Percentage: {body_metrics.subcutaneous_fat_percentage:.1f}%")
            print(f"Visceral Fat Value: {body_metrics.visceral_fat_value}")
            print(f"Body Water Percentage: {body_metrics.body_water_percentage:.1f}%")
            print(f"Basal Metabolic Rate: {body_metrics.basal_metabolic_rate} calories")
            print(f"Skeletal Muscle Percentage: {body_metrics.skeletal_muscle_percentage:.1f}%")
            print(f"Muscle Mass: {body_metrics.muscle_mass:.2f} kg")
            print(f"Bone Mass: {body_metrics.bone_mass:.2f} kg")
            print(f"Protein Percentage: {body_metrics.protein_percentage:.1f}%")
            print(f"Metabolic Age: {body_metrics.metabolic_age} years")

    # Create scale (replace XX:XX:XX:XX:XX:XX with your scale's Bluetooth address)
    scale = ESF551Scale("XX:XX:XX:XX:XX:XX", notification_callback)
    scale.display_unit = WeightUnit.KG  # Set display unit to kilograms

    await scale.async_start()
    await asyncio.sleep(30)  # Wait for measurements
    await scale.async_stop()

asyncio.run(main())
```

## Multi-Model Usage

For different scale models:

```python
# ESF-551 (full features)
from etekcity_esf551_ble import ESF551Scale
scale = ESF551Scale(address, callback)

# EFS-A591S / Apex HR (experimental, encrypted)
from etekcity_esf551_ble import EFSA591SScale
scale = EFSA591SScale(address, callback)

# ESF-24, ESF-17 and ESF-18 (experimental — they share the ESF-24's protocol
# and client class)
from etekcity_esf551_ble import ESF24Scale
scale = ESF24Scale(address, callback)

# FIT-8S (experimental, advertisement-based — no GATT connection)
from etekcity_esf551_ble import FIT8SScale
scale = FIT8SScale(address, callback)

# EFS-C651 (experimental, encrypted)
from etekcity_esf551_ble import EFSC651Scale
scale = EFSC651Scale(address, callback)
```

For a real-life usage example of this library, check out the [Etekcity Fitness Scale BLE Integration for Home Assistant](https://github.com/ronnnnnnnnnnnnn/etekcity_fitness_scale_ble).


## Model Detection

The library provides helpers to classify a BLE advertisement into a `ScaleModel` via `detect_model(local_name, manufacturer_data, address=None)`, returning `None` for unrecognized devices. Combined with `SCALE_CLASSES`, this removes the need to know your scale's model (or even its address) up front — scan, classify, and connect with the right client. Here's a basic example of how to use it:

```python
import asyncio

from bleak import BleakScanner

from etekcity_esf551_ble import SCALE_CLASSES, ScaleData, WeightUnit, detect_model


async def find_scale(timeout: float = 30.0):
    """Return (address, model) of the first recognized scale that advertises."""
    found = asyncio.get_running_loop().create_future()

    def on_advertisement(device, adv):
        model = detect_model(adv.local_name, adv.manufacturer_data, device.address)
        if model is not None and not found.done():
            found.set_result((device.address, model))

    async with BleakScanner(on_advertisement):
        # Some models only advertise while in use, so step on the scale.
        return await asyncio.wait_for(found, timeout)


def on_measurement(data: ScaleData) -> None:
    print(f"{data.measurements['weight']} kg  ({data.display_unit.name})")


async def main():
    address, model = await find_scale()
    print(f"Found {model.value} at {address}")

    scale = SCALE_CLASSES[model](address, on_measurement, WeightUnit.KG)
    await scale.async_start()
    await asyncio.sleep(60)  # step on the scale
    await scale.async_stop()


asyncio.run(main())
```

Note for macOS: CoreBluetooth reports devices by UUID rather than MAC address; construct the scanner with `BleakScanner(on_advertisement, cb={"use_bdaddr": True})` so `detect_model()` can validate the MAC echoes (and so the EFS-A591S and EFS-C651 clients, whose session keys derive from the MAC, can connect).

Two manufacturer-data frame families, both observed in real advertisement captures:

**Company ID 1744 (Etekcity platform):** `[0]=0x01, [1:7]=device MAC little-endian, [7:9]=model identifier BE16, [9:]=model-specific payload`

**Company ID 65535 (QN platform, ESF-24):** `[0:2]=model identifier BE16, [2]=0x01, [3]=varies (undecoded), [4]=pending stored-record count, [5:11]=device MAC little-endian`

| Model | Company | Codes |
|---|---|---|
| ESF-551 | 1744 | 1 (0x0001), 2 (0x0002) |
| EFS-A591S | 1744 | 3 (0x0003), 5 (0x0005), 127 (0x007F), 134 (0x0086) |
| EFS-C651 | 1744 | 136 (0x0088) |
| FIT-8S | 1744 | 49321 (0xC0A9) |
| ESF-24 | 65535 | 294 (0x0126), 946 (0x03B2) |
| ESF-17 | 65535 | 211 (0x00D3) |
| ESF-18 | 65535 | 671 (0x029F) |

Identifiers are compared as the full 16-bit value, with frame-shape and MAC-echo validation. Codes for other variants are added as units are reported — when a name/address fallback matcher identifies a device whose identifier isn't in the registry yet, `detect_model` logs the identifier so it can be reported and added to the registry — and those fallback matchers cover unlisted variants in the meantime.


## API Reference

### Scale Classes

The scale classes form a small hierarchy by transport:

```
EtekcitySmartFitnessScale (abstract: scanning + lifecycle + callback)
├── GattScale (abstract: GATT connection + cooldown_seconds) → ESF551Scale, ESF24Scale, EFSA591SScale
└── AdvertisementScale (abstract: reads advertisements; unit observed-only) → FIT8SScale
```

#### `EtekcitySmartFitnessScale` (Abstract Base)

Transport-agnostic base shared by every model: BLE scanning, lifecycle (`async_start` / `async_stop`), the notification callback and the `display_unit` / `hw_version` / `sw_version` properties.

#### `GattScale` (Abstract)

Base for scales that deliver measurements over a GATT connection. Adds the connection lifecycle and the `cooldown_seconds` option. Subclassed by `ESF551Scale`, `ESF24Scale` and `EFSA591SScale`.

#### `AdvertisementScale` (Abstract)

Base for scales that read measurements passively from BLE advertisements, with no GATT connection. Subclassed by `FIT8SScale`. On these scales `display_unit` is observed from the advertisement and cannot be set.

#### `ESF551Scale`

Implementation for ESF-551 scales with full feature support.

#### `ESF24Scale`

Experimental implementation for ESF-24 scales — and for the ESF-17/18, which speaks the same protocol and shares this client class. Reports weight and dual-band BIA impedance: the 50 kHz value under `IMPEDANCE_KEY` (usable with `BodyMetrics`) and the raw 500 kHz value under `IMPEDANCE_500KHZ_KEY` (ESF-24 and ESF-17/ only).

Accepts the keyword-only argument `clear_stored_measurements: bool = False`. When enabled, the library drains the scale's store of offline measurements — readings taken while nothing was connected — once per session. Receiving a stored reading deletes it from the scale (the protocol has no separate delete command), so enabling this hides those readings from any other client: leave it off if you also sync the scale with the official VeSync app. Drained readings are logged at debug level and discarded for now.

#### `FIT8SScale`

Experimental implementation for FIT-8S scales. Reads weight and impedance passively from BLE advertisement manufacturer data — no GATT connection is established.

#### `EFSA591SScale`

Experimental implementation for EFS-A591S (Apex HR) scales. Uses an encrypted protocol over GATT with a Diffie-Hellman key exchange and AES-128-CBC encryption, requiring the device's real Bluetooth MAC address for key derivation. Some Apex firmwares instead stream their measurements unencrypted; those are handled too (no key needed). Supports weight, impedance, heart rate and display unit management.

#### `EFSC651Scale`

Experimental implementation for EFS-C651 scales. Uses the same encrypted protocol as the EFS-A591S, and likewise requires the device's real Bluetooth MAC address for key derivation. Supports weight, impedance and display unit management; this model has no heart-rate sensor. Impedance is reported in an encoded form specific to this model and is decoded into ohms by the library.

#### Common Methods:

- `__init__(self, address: str, notification_callback: Callable[[ScaleData], None], display_unit: WeightUnit = None, scanning_mode: BluetoothScanningMode = BluetoothScanningMode.ACTIVE, adapter: str | None = None, bleak_scanner_backend: BaseBleakScanner = None, logger: logging.Logger | None = None)`
  - GATT-based scales (`ESF551Scale`, `ESF24Scale`, `EFSA591SScale`) additionally accept `cooldown_seconds: int = 5` — ignore advertisements for that many seconds after a disconnection.
- `async_start()`: Start scanning for the scale (GATT-based models connect on detection).
- `async_stop()`: Stop scanning and disconnect.

#### Common Properties:

- `display_unit`: Get or set the display unit (WeightUnit.KG, WeightUnit.LB or WeightUnit.ST). Returns None if the display unit is currently unknown (not set by the user and not yet received from the scale together with a stable weight measurement). On advertisement-based scales (`FIT8SScale`) the unit is observed from the advertisement and is read-only — assignments are ignored.
- `hw_version`: Get the hardware version of the scale (read-only).
- `sw_version`: Get the software version of the scale (read-only).



### `WeightUnit`

An enum representing the possible display units:

- `WeightUnit.KG`: Kilograms
- `WeightUnit.LB`: Pounds
- `WeightUnit.ST`: Stones

### `ScaleData`

A dataclass containing scale measurement data:

- `name`: Scale name
- `address`: Scale Bluetooth address
- `hw_version`: Hardware version
- `sw_version`: Software version
- `display_unit`: Current display unit (concerns only the weight as displayed on the scale, the measurement itself is always provided by the API in kilograms)
- `measurements`: Dictionary of measurements (currently supports: weight in kilograms, impedance in ohms — plus a second 500 kHz impedance under `IMPEDANCE_500KHZ_KEY` on the ESF-24 — and heart rate in bpm)

### `BodyMetrics`

A class for calculating various body composition metrics based on height, age, sex and the weight and impedance as measured by the scale, similar to the metrics calculated and shown in the VeSync app.

#### Methods:

- `__init__(self, weight_kg: float, height_m: float, age: int, sex: Sex, impedance: int, athlete: bool = False)`
- `as_dict(self) -> dict[str, int | float]`: All of the calculated metrics below, keyed by property name. The constructor inputs are not included.

#### Properties:

- `body_mass_index`: Body Mass Index (BMI)
- `body_fat_percentage`: Estimated body fat percentage
- `fat_free_weight`: Weight of non-fat body mass in kg
- `subcutaneous_fat_percentage`: Estimated subcutaneous fat percentage
- `visceral_fat_value`: Estimated visceral fat level (unitless)
- `body_water_percentage`: Estimated body water percentage
- `basal_metabolic_rate`: Estimated basal metabolic rate in calories
- `skeletal_muscle_percentage`: Estimated skeletal muscle percentage
- `muscle_mass`: Estimated muscle mass in kg
- `bone_mass`: Estimated bone mass in kg
- `protein_percentage`: Estimated protein percentage
- `weight_score`: Calculated weight score (0-100)
- `fat_score`: Calculated fat score (0-100)
- `bmi_score`: Calculated BMI score (0-100)
- `health_score`: Overall health score based on other metrics (0-100)
- `metabolic_age`: Estimated metabolic age in years

### `BodyMetricsV2`

The calculator matching the VeSync app for the **EFS-C651**. Takes the same constructor arguments as `BodyMetrics` and provides the same `as_dict()` method.

This algorithm estimates lean body mass first and derives everything else from it, working in fixed-point arithmetic throughout. Its values therefore land on 0.1 steps — that is the algorithm's real precision, not rounding applied afterwards.

#### Properties:

All of the `BodyMetrics` properties above **except** `weight_score`, `fat_score`, `bmi_score` and `health_score`, plus:

- `body_fat_mass`: Estimated body fat in kg
- `muscle_percentage`: Estimated muscle mass as a percentage of total weight
- `skeletal_muscle_mass`: Estimated skeletal muscle in kg

### `calc_age`

`calc_age(birthdate: date) -> int`

Age in whole years as of today, counted the way the scale's app counts it: a birthday that hasn't occurred yet this year isn't counted. Convenient for the `age` argument of `BodyMetrics`.

```python
from datetime import date
from etekcity_esf551_ble import BodyMetrics, Sex, calc_age

body_metrics = BodyMetrics(
    weight_kg=75.0,
    height_m=1.75,
    age=calc_age(date(1990, 5, 17)),
    sex=Sex.Male,
    impedance=500,
)
print(body_metrics.as_dict())
```

### `Sex`

An enum representing biological sex for body composition calculations:

- `Sex.Male`
- `Sex.Female`

### `BluetoothScanningMode`

Enum for BLE scanning mode (Linux only; other platforms use active scanning):

- `BluetoothScanningMode.ACTIVE` (default)
- `BluetoothScanningMode.PASSIVE`


## Compatibility

- Python 3.11+
- bleak 2.x or 3.x (`bleak>=2.0.0,<4.0.0`)
- Tested on Mac (Apple Silicon) and Raspberry Pi 4
- Compatibility with Windows is unknown


## Troubleshooting

On Raspberry Pi 4 (and possibly other Linux machines using BlueZ), if you encounter a `org.bluez.Error.InProgress` error, try the following in `bluetoothctl`:

```
power off
power on
scan on
```
(See https://github.com/home-assistant/core/issues/76186#issuecomment-1204954485)


## Acknowledgments

- FIT-8S protocol support contributed by [@Flautz](https://github.com/Flautz) — thank you!
- EFS-A591S (Apex HR) protocol support contributed by [@r3klawz](https://github.com/r3klawz) — thank you!
- EFS-C651 protocol support contributed by [@tobsen111](https://github.com/tobsen111) — thank you!
- EFS-A591S plaintext-firmware support contributed by [@gthelding](https://github.com/gthelding) — thank you!


## Support the Project

If you find this unofficial project helpful, consider buying me a coffee! Your support helps maintain and improve this library.

[![Buy Me A Coffee](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/ronnnnnnn)


## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.


## Disclaimer

This is an independent project developed by the community. It is not endorsed by, directly affiliated with, maintained, authorized or sponsored by Etekcity, VeSync or any of their affiliates or subsidiaries. All product and company names are the registered trademarks of their original owners. The use of any trade name or trademark is for identification and reference purposes only and does not imply any association with the trademark holder of their product brand.
