# Etekcity ESF-551, ESF-24, FIT-8S & EFS-A591S BLE

This package provides a basic unofficial interface for interacting with Etekcity Smart Fitness Scales using Bluetooth Low Energy (BLE). It supports the [Etekcity ESF-551](https://etekcity.com/products/smart-fitness-scale-esf551), [Etekcity ESF-24](https://us.vesync.com/product-detail/etekcity-esf24-smart-fitness-scale-335), [Etekcity FIT-8S](https://etekcity.com/products/smart-fitness-scale-fit-8s) and [Etekcity EFS-A591S (Apex HR)](https://etekcity.com/products/hr-smart-fitness-scale) models.

## Features

- **ESF-551**: Fully supported and stable (weight, impedance, body metrics, display unit management)
- **ESF-24**: Experimental support (weight, unit changes)
- **FIT-8S**: Experimental support (weight, impedance, body metrics)
- **EFS-A591S (Apex HR)**: Experimental support (weight, impedance, heart rate, body metrics, unit changes)
- Easy connection and notification handling
- Body composition metrics via the `BodyMetrics` calculator — works with any impedance-capable scale (ESF-551, EFS-A591S and FIT-8S only)
- Display unit management (ESF-551, EFS-A591S and ESF-24 only, programmatic display unit control isn't supported on advertisement-based scales)

## Supported Models

| Model | Status | Features |
|-------|--------|----------|
| ESF-551 | ✅ Fully Supported | Weight, impedance, body metrics, unit changes |
| EFS-A591S | 🔬 Experimental | Weight, impedance, heart rate, body metrics, unit changes |
| ESF-24 | 🔬 Experimental | Weight, unit changes |
| FIT-8S | 🔬 Experimental | Weight, impedance, body metrics |

**Disclaimer: This is an unofficial, community-developed library. It is not affiliated with, officially maintained by or in any way officially connected with Etekcity, VeSync Co., Ltd. (the owner of the Etekcity brand) or any of their subsidiaries or affiliates. The official Etekcity website can be found at https://www.etekcity.com, and the official VeSync website at https://www.vesync.com. The names "Etekcity" and "VeSync" as well as related names, marks, emblems and images are registered trademarks of their respective owners.**

[![Buy Me A Coffee](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/ronnnnnnn)


## Installation

Requires Python 3.10+ and bleak 2.x or 3.x. Install using pip:

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

            # Calculate body metrics (ESF-551, EFS-A591S and FIT-8S only)
            # Note: Replace with your actual height, age and sex
            body_metrics = BodyMetrics(
                weight_kg=data.measurements[WEIGHT_KEY],
                height_m=1.75,  # Example height
                age=30,  # Example age
                sex=Sex.Male,  # Example sex
                impedance=data.measurements[IMPEDANCE_KEY]
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

# ESF-24 (experimental)
from etekcity_esf551_ble import ESF24Scale
scale = ESF24Scale(address, callback)

# FIT-8S (experimental, advertisement-based — no GATT connection)
from etekcity_esf551_ble import FIT8SScale
scale = FIT8SScale(address, callback)
```

For a real-life usage example of this library, check out the [Etekcity Fitness Scale BLE Integration for Home Assistant](https://github.com/ronnnnnnnnnnnnn/etekcity_fitness_scale_ble).


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

Experimental implementation for ESF-24 scales (weight only).

#### `FIT8SScale`

Experimental implementation for FIT-8S scales. Reads weight and impedance passively from BLE advertisement manufacturer data — no GATT connection is established.

#### `EFSA591SScale`

Experimental implementation for EFS-A591S (Apex HR) scales. Uses an encrypted protocol over GATT with a Diffie-Hellman key exchange and AES-128-CBC encryption. Supports weight, impedance, heart rate and display unit management. Requires the device's real Bluetooth MAC address for key derivation.

#### Common Methods:

- `__init__(self, address: str, notification_callback: Callable[[ScaleData], None], display_unit: WeightUnit = None, scanning_mode: BluetoothScanningMode = BluetoothScanningMode.ACTIVE, adapter: str | None = None, bleak_scanner_backend: BaseBleakScanner = None, logger: logging.Logger | None = None)`
  - GATT-based scales (`ESF551Scale`, `ESF24Scale`, `EFSA591SScale`) additionally accept `cooldown_seconds: int = 0` — ignore advertisements for that many seconds after a disconnection. It does not apply to advertisement-based scales such as `FIT8SScale`.
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
- `measurements`: Dictionary of measurements (currently supports: weight in kilograms, impedance in ohms and heart rate in bpm)

### `BodyMetrics`

A class for calculating various body composition metrics based on height, age, sex and the weight and impedance as measured by the scale, similar to the metrics calculated and shown in the VeSync app. Note that currently "Athlete Mode" is not supported.

#### Methods:

- `__init__(self, weight_kg: float, height_m: float, age: int, sex: Sex, impedance: int)`

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

### `Sex`

An enum representing biological sex for body composition calculations:

- `Sex.Male`
- `Sex.Female`

### `BluetoothScanningMode`

Enum for BLE scanning mode (Linux only; other platforms use active scanning):

- `BluetoothScanningMode.ACTIVE` (default)
- `BluetoothScanningMode.PASSIVE`


## Compatibility

- Python 3.10+
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


## Support the Project

If you find this unofficial project helpful, consider buying me a coffee! Your support helps maintain and improve this library.

[![Buy Me A Coffee](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/ronnnnnnn)


## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.


## Disclaimer

This is an independent project developed by the community. It is not endorsed by, directly affiliated with, maintained, authorized or sponsored by Etekcity, VeSync or any of their affiliates or subsidiaries. All product and company names are the registered trademarks of their original owners. The use of any trade name or trademark is for identification and reference purposes only and does not imply any association with the trademark holder of their product brand.
