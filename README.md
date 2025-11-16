# Etekcity ESF-551 & ESF-24 BLE

This package provides a basic unofficial interface for interacting with Etekcity Smart Fitness Scales using Bluetooth Low Energy (BLE). It supports both the [Etekcity ESF-551](https://etekcity.com/products/smart-fitness-scale-esf551) and [Etekcity ESF-24](https://etekcity.com/products/esf24-smart-fitness-scale) models.

## Features

- **ESF-551**: Full feature support including weight, impedance, body metrics, and display unit management
- **ESF-24**: Experimental weight-only support (kilograms only, protocol under analysis)
- Easy connection and notification handling
- Body metrics calculations (ESF-551 only)
- Display unit management (ESF-551 only)

## Supported Models

| Model | Status | Features |
|-------|--------|----------|
| ESF-551 | ✅ Fully Supported | Weight, impedance, body metrics, unit changes |
| ESF-24 | 🔬 Experimental | Weight, impedance, unit changes |

## Version Status

**v0.4.0-beta.3** (Pre-Release):
- ✅ ESF-551: Fully supported and stable
- 🔬 ESF-24: Experimental support (protocol analysis ongoing)
- ♻️ Internal: passive-scan optimisation & universal2 wheel build
- ⚠️ Breaking changes from v0.3.x (architecture refactoring)

**Note**: This is a pre-release version. PyPI will not automatically suggest upgrades from stable versions (v0.3.x) to this beta version.

**Disclaimer: This is an unofficial, community-developed library. It is not affiliated with, officially maintained by, or in any way officially connected with Etekcity, VeSync Co., Ltd. (the owner of the Etekcity brand), or any of their subsidiaries or affiliates. The official Etekcity website can be found at https://www.etekcity.com, and the official VeSync website at https://www.vesync.com. The names "Etekcity" and "VeSync" as well as related names, marks, emblems and images are registered trademarks of their respective owners.**

[![Buy Me A Coffee](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/ronnnnnnn)


## Installation

Install the package using pip:

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

            # Calculate body metrics (ESF-551 only)
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

# ESF-24 (experimental)
from etekcity_esf551_ble import ESF24Scale
scale = ESF24Scale(address, callback)
```

For a real-life usage example of this library, check out the [Etekcity Fitness Scale BLE Integration for Home Assistant](https://github.com/ronnnnnnnnnnnnn/etekcity_fitness_scale_ble).


## API Reference

### Scale Classes

#### `EtekcitySmartFitnessScale` (Abstract Base)

Abstract base class for all scale implementations.

#### `ESF551Scale`

Implementation for ESF-551 scales with full feature support.

#### `ESF24Scale`

Experimental implementation for ESF-24 scales (weight-only).

#### Common Methods:

- `__init__(self, address: str, notification_callback: Callable[[ScaleData], None], display_unit: WeightUnit = None)`
- `async_start()`: Start scanning for and connecting to the scale.
- `async_stop()`: Stop the connection to the scale.

#### Common Properties:

- `display_unit`: Get or set the display unit (WeightUnit.KG, WeightUnit.LB or WeightUnit.ST). Returns None if the display unit is currently unknown (not set by the user and not yet received from the scale together with a stable weight measurement).
- `hw_version`: Get the hardware version of the scale (read-only).
- `sw_version`: Get the software version of the scale (read-only).

### `ESF551ScaleWithBodyMetrics`

An extended version of ESF551Scale that automatically calculates body metrics.

#### Methods:

- `__init__(self, address: str, notification_callback: Callable[[ScaleData], None], sex: Sex, birthdate: date, height_m: float, display_unit: WeightUnit = None)`
- `async_start()`: Start scanning for and connecting to the scale.
- `async_stop()`: Stop the connection to the scale.

#### Properties:

- `display_unit`: Get or set the display unit (WeightUnit.KG, WeightUnit.LB or WeightUnit.ST). Returns None if the display unit is currently unknown (not set by the user and not yet received from the scale together with a stable weight measurement).
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
- `measurements`: Dictionary of measurements (currently supports: weight in kilograms and impedance in ohms)

### `BodyMetrics`

A class for calculating various body composition metrics based on height, age, sex, and the weight and impedance as measured by the scale, similar to the metrics calculated and shown in the VeSync app. Note that currently "Athlete Mode" is not supported.

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


## Compatibility

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


## Support the Project

If you find this unofficial project helpful, consider buying me a coffee! Your support helps maintain and improve this library.

[![Buy Me A Coffee](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/ronnnnnnn)


## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.


## Disclaimer

This is an independent project developed by the community. It is not endorsed by, directly affiliated with, maintained, authorized, or sponsored by Etekcity, VeSync Co., Ltd., or any of their affiliates or subsidiaries. All product and company names are the registered trademarks of their original owners. The use of any trade name or trademark is for identification and reference purposes only and does not imply any association with the trademark holder of their product brand.
