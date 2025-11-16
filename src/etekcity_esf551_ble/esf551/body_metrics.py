from collections.abc import Callable
from datetime import date
from enum import IntEnum
from functools import cached_property
from math import floor

from bleak.backends.scanner import BaseBleakScanner

from ..const import IMPEDANCE_KEY, WEIGHT_KEY
from ..parser import (
    BluetoothScanningMode,
    ScaleData,
    WeightUnit,
)
from .parser import ESF551Scale


class Sex(IntEnum):
    Male = 0
    Female = 1


class BodyMetrics:
    """
    Class for calculating various body composition metrics based on weight, height, age, sex, and impedance.
    """

    def __init__(
        self, weight_kg: float, height_m: float, age: int, sex: Sex, impedance: int
    ):
        """
        Initialize body metrics calculator.

        Args:
            weight_kg: Weight in kilograms
            height_m: Height in meters
            age: Age in years
            sex: Biological sex (Male or Female)
            impedance: Bioelectrical impedance measurement from the scale in ohms
        """
        self.weight = weight_kg
        self.height = height_m
        self.age = age
        self.sex = sex
        self.impedance = impedance

    @cached_property
    def body_mass_index(self) -> float:
        """
        Calculate Body Mass Index (BMI).

        BMI is a measure of body fat based on height and weight.

        Returns:
            float: The calculated BMI value.
        """
        return floor(self.weight / (self.height**2) * 100) / 100

    @cached_property
    def body_fat_percentage(self) -> float:
        """
        Calculate Body Fat Percentage (BFP).

        BFP is the total mass of fat divided by total body mass, multiplied by 100.

        Returns:
            float: The calculated BFP value.
        """
        age_factor = [0.103, 0.097]
        bmi_factor = [1.524, 1.545]
        constant = [22, 12.7]

        bfp = floor((age_factor[self.sex] * self.age + 
               bmi_factor[self.sex] * self.body_mass_index - 
               500/self.impedance - constant[self.sex]) * 10) / 10
        return max(5, min(75, bfp))

    @cached_property
    def fat_free_weight(self) -> float:
        """
        Calculate Fat-Free Weight (FFW).

        FFW is the difference between total body weight and body fat weight.

        Returns:
            float: The calculated FFW value in kg.
        """
        return round(self.weight * (1 - self.body_fat_percentage / 100), 2)

    @cached_property
    def subcutaneous_fat_percentage(self) -> float:
        """
        Calculate Subcutaneous Fat Percentage.

        Subcutaneous Fat is the fat that lies just beneath the skin.

        Returns:
            float: The calculated subcutaneous fat percentage value.
        """
        bfp_factor = [0.965, 0.983]
        vfv_factor = [0.22, 0.303]
        return round(bfp_factor[self.sex] * self.body_fat_percentage - 
                vfv_factor[self.sex] * self.visceral_fat_value, 1)

    @cached_property
    def visceral_fat_value(self) -> int:
        """
        Calculate Visceral Fat Value.

        Visceral Fat Value is a unitless measure of the level of fat stored in the abdominal cavity.

        Returns:
            int: The calculated visceral fat value, between 1 and 30.
        """
        bmi_factor = [0.8666, 0.8895]
        bfp_factor = [0.0082, 0.0943]
        fat_factor = [0.026, -0.0534]
        constant = [14.2692, 16.215]
        vfv = int(bmi_factor[self.sex] * self.body_mass_index + 
               bfp_factor[self.sex] * self.body_fat_percentage + 
               fat_factor[self.sex] * (self.weight - self.fat_free_weight) - 
               constant[self.sex])
        return max(1, min(30, vfv))

    @cached_property
    def body_water_percentage(self) -> float:
        """
        Calculate Body Water Percentage (BWP).

        BWP is the total amount of water in the body as a percentage of total weight.

        Returns:
            float: The calculated BWP value.
        """
        ff1_factor = [0.05, 0.06]
        ff2_factor = [0.76, 0.73]
        ff1 = max(1, ff1_factor[self.sex] * self.fat_free_weight)
        bwp = round(ff2_factor[self.sex] * (self.fat_free_weight - ff1) / self.weight * 100, 1)
        return max(10, min(80, bwp))

    @cached_property
    def basal_metabolic_rate(self) -> int:
        """
        Calculate Basal Metabolic Rate (BMR).

        BMR is the number of calories required to keep your body functioning at rest.

        Returns:
            int: The calculated BMR value.
        """
        bmr = int(self.fat_free_weight * 21.6 + 370)
        return max(900, min(2500, bmr))

    @cached_property
    def skeletal_muscle_percentage(self) -> float:
        """
        Calculate Skeletal Muscle Percentage.

        Skeletal muscle is the muscle tissue directly connected to bones.

        Returns:
            float: The calculated skeletal muscle percentage value.
        """
        ff1_factor = [0.05, 0.06]
        ff2_factor = [0.68, 0.62]
        ff1 = max(1, ff1_factor[self.sex] * self.fat_free_weight)
        return round(ff2_factor[self.sex] * (self.fat_free_weight - ff1) / self.weight * 100, 1)

    @cached_property
    def muscle_mass(self) -> float:
        """
        Calculate Muscle Mass.

        Returns:
            float: The calculated muscle mass value in kg.
        """
        ffw_factor = [0.05, 0.06]
        ff = max(1, ffw_factor[self.sex] * self.fat_free_weight)
        return round(self.fat_free_weight - ff, 2)

    @cached_property
    def bone_mass(self) -> float:
        """
        Calculate Bone Mass.

        Bone mass is the total mass of the bones in the body.

        Returns:
            float: The calculated Bone Mass value in kg.
        """
        ffw_factor = [0.05, 0.06]
        return max(1, round(ffw_factor[self.sex] * self.fat_free_weight, 2))

    @cached_property
    def protein_percentage(self) -> float:
        """
        Calculate Protein Percentage.

        Protein percentage is the percentage of total body weight that is made up of proteins.

        Returns:
            float: The calculated protein percentage value.
        """
        bfp_factor = [1, 1.05]
        bpp = round(100 - bfp_factor[self.sex] * self.body_fat_percentage - 
               self.bone_mass / self.weight * 100 - self.body_water_percentage, 1)
        return max(5, bpp)

    @cached_property
    def weight_score(self) -> int:
        """
        Calculate Weight Score.

        Weight Score is a measure of how close the person's weight is to their ideal weight.

        Returns:
            int: The calculated Weight Score, ranging from 0 to 100.
        """
        height_factor = [100, 137]
        constant = [80, 110]
        factor = [0.7, 0.45]
        res = factor[self.sex] * (height_factor[self.sex] * self.height - constant[self.sex])
        if res <= self.weight:
            if res * 1.3 < self.weight:
                return 50
            return int(100 - 50 * (self.weight - res) / (0.3 * res))
        if res * 0.7 < self.weight:
            return int(100 - 50 * (res - self.weight) / (0.3 * res))
        for x in range(6):
            if res * x / 10 > self.weight:
                return x * 10
        return 0

    @cached_property
    def fat_score(self) -> int:
        """
        Calculate Fat Score.

        Fat Score is a measure of how close the person's body fat percentage is to the ideal range.

        Returns:
            int: The calculated Fat Score, ranging from 0 to 100.
        """
        constant = [16, 26]
        if constant[self.sex] < self.body_fat_percentage:
            if self.body_fat_percentage >= 45:
                return 50
            return int(100 - 50 * (self.body_fat_percentage - constant[self.sex]) / (45 - constant[self.sex]))
        return int(100 - 50 * (constant[self.sex] - self.body_fat_percentage) / (constant[self.sex] - 5))

    @cached_property
    def bmi_score(self) -> int:
        """
        Calculate BMI Score.

        BMI Score is a measure of how close the person's BMI is to the ideal range.

        Returns:
            int: The calculated BMI Score.
        """
        if self.body_mass_index >= 22:
            if self.body_mass_index >= 35:
                return 50
            return int(100 - 3.85 * (self.body_mass_index - 22))
        if self.body_mass_index >= 15:
            return int(100 - 3.85 * (22 - self.body_mass_index))
        if self.body_mass_index >= 10:
            return 40
        if self.body_mass_index >= 5:
            return 30
        return 20

    @cached_property
    def health_score(self) -> int:
        """
        Calculate Health Score.

        Health Score is an overall measure of body composition health based on weight, fat, and BMI scores.

        Returns:
            int: The calculated Health Score, ranging from 0 to 100.
        """
        return (self.weight_score + self.fat_score + self.bmi_score) // 3

    @cached_property
    def metabolic_age(self) -> int:
        """
        Calculate Metabolic Age.

        Metabolic Age is an estimate of the body's metabolic rate compared to average values.

        Returns:
            int: The calculated Metabolic Age, with a minimum of 18.
        """
        if self.health_score < 50:
            age_adjustment_factor = 0
        elif self.health_score < 60:
            age_adjustment_factor = 1
        elif self.health_score < 65:
            age_adjustment_factor = 2
        elif self.health_score < 68:
            age_adjustment_factor = 3
        elif self.health_score < 70:
            age_adjustment_factor = 4
        elif self.health_score < 73:
            age_adjustment_factor = 5
        elif self.health_score < 75:
            age_adjustment_factor = 6
        elif self.health_score < 80:
            age_adjustment_factor = 7
        elif self.health_score < 85:
            age_adjustment_factor = 8
        elif self.health_score < 88:
            age_adjustment_factor = 9
        elif self.health_score < 90:
            age_adjustment_factor = 10
        elif self.health_score < 93:
            age_adjustment_factor = 11
        elif self.health_score < 95:
            age_adjustment_factor = 12
        elif self.health_score < 97:
            age_adjustment_factor = 13
        elif self.health_score < 98:
            age_adjustment_factor = 14
        elif self.health_score < 99:
            age_adjustment_factor = 15
        else:
            age_adjustment_factor = 16

        return max(18, self.age + 8 - age_adjustment_factor)


def _calc_age(birthdate: date) -> int:
    today = date.today()
    years = today.year - birthdate.year
    if today.month < birthdate.month or (today.month == birthdate.month and today.day < birthdate.day):
        years -= 1
    return years


def _as_dictionary(obj: BodyMetrics) -> dict[str, int | float]:
    return {prop: getattr(obj, prop) for prop in dir(obj) if not prop.startswith("__")}


class ESF551ScaleWithBodyMetrics(ESF551Scale):
    """
    Extended ESF-551 scale implementation with body metrics calculations.

    This class extends the ESF-551 scale implementation to automatically calculate
    body composition metrics based on the user's profile (sex, age, height)
    and the measurements from the scale (weight, impedance).

    All the body metrics are added to the ScaleData.measurements dictionary
    before being passed to the notification callback.
    """

    def __init__(
        self,
        address: str,
        notification_callback: Callable[[ScaleData], None],
        sex: Sex,
        birthdate: date,
        height_m: float,
        display_unit: WeightUnit = None,
        scanning_mode: BluetoothScanningMode = BluetoothScanningMode.ACTIVE,
        adapter: str | None = None,
        bleak_scanner_backend: BaseBleakScanner = None,
    ) -> None:
        """
        Initialize the scale interface with body metrics calculation.

        Args:
            address: Bluetooth address of the scale
            notification_callback: Function to call when weight data is received
            sex: Biological sex of the user (Male or Female)
            birthdate: Date of birth of the user
            height_m: Height of the user in meters
            display_unit: Preferred weight unit (KG, LB, or ST). If specified,
                          the scale will be instructed to change its display unit
                          to this value upon connection.
            scanning_mode: Mode for BLE scanning (ACTIVE or PASSIVE).
            adapter: Bluetooth adapter to use (Linux only).
            bleak_scanner_backend: Optional custom BLE scanner backend.
        """
        self._sex = sex
        self._birthdate = birthdate
        self._height_m = height_m
        self._original_callback = notification_callback

        # Initialize the parent ESF551Scale
        super().__init__(
            address,
            lambda data: self._wrapped_notification_callback(
                self._sex, self._birthdate, self._height_m, data
            ),
            display_unit,
            scanning_mode,
            adapter,
            bleak_scanner_backend,
        )

    def _wrapped_notification_callback(
        self, sex: Sex, birthdate: date, height_m: float, data: ScaleData
    ) -> None:
        data.measurements |= _as_dictionary(
            BodyMetrics(
                data.measurements[WEIGHT_KEY],
                height_m,
                _calc_age(birthdate),
                sex,
                data.measurements[IMPEDANCE_KEY],
            )
        )
        self._original_callback(data)
