"""Body-composition metrics derived from a weight and impedance measurement.

Scales report weight and a bioelectrical impedance reading; every other figure
is derived. The vendor app pairs different scale models with different
derivation algorithms, so one implementation is provided per algorithm:

- :class:`BodyMetrics` — matches the app for the ESF-551, FIT-8S and ESF-24
  (and, by report, the EFS-A591S).
- :class:`BodyMetricsV2` — matches the app for the EFS-C651.

Both provide the metrics declared on :class:`BaseBodyMetrics`, so they can be
used interchangeably; each also exposes a few metrics of its own. See each
class's docstring for the models it is known to align with, and on what
evidence.
"""

import abc
from datetime import date
from enum import IntEnum
from functools import cached_property
from math import floor


class Sex(IntEnum):
    Male = 0
    Female = 1


class BaseBodyMetrics(abc.ABC):
    """Metrics every body-composition implementation provides.

    Subclasses differ in the algorithm they reproduce, and therefore in their
    exact numbers, but all of them expose the twelve properties declared here.
    Individual implementations may expose further metrics of their own; see
    their docstrings.
    """

    def __init__(
        self,
        weight_kg: float,
        height_m: float,
        age: int,
        sex: Sex,
        impedance: int,
        athlete: bool = False,
    ):
        """Initialize a body metrics calculator.

        Args:
            weight_kg: Weight in kilograms
            height_m: Height in meters
            age: Age in years
            sex: Biological sex (Male or Female)
            impedance: Bioelectrical impedance measurement from the scale in ohms
            athlete: Athletic body type flag (default: False)
                     Adjusts the body fat percentage (and, through it, every
                     downstream metric) for athletic body types.
        """
        self.weight = weight_kg
        self.height = height_m
        self.age = age
        self.sex = sex
        self.impedance = impedance
        self.athlete = athlete

    @property
    @abc.abstractmethod
    def body_mass_index(self) -> float:
        """Body Mass Index (BMI), from height and weight alone."""

    @property
    @abc.abstractmethod
    def body_fat_percentage(self) -> float:
        """Body fat as a percentage of total body mass."""

    @property
    @abc.abstractmethod
    def fat_free_weight(self) -> float:
        """Total body weight minus body fat weight, in kg."""

    @property
    @abc.abstractmethod
    def subcutaneous_fat_percentage(self) -> float:
        """Fat lying just beneath the skin, as a percentage."""

    @property
    @abc.abstractmethod
    def visceral_fat_value(self) -> int:
        """Unitless index of fat stored in the abdominal cavity.

        Implementations differ in the range they report; see each one.
        """

    @property
    @abc.abstractmethod
    def body_water_percentage(self) -> float:
        """Total body water as a percentage of total weight."""

    @property
    @abc.abstractmethod
    def basal_metabolic_rate(self) -> int:
        """Calories required to keep the body functioning at rest."""

    @property
    @abc.abstractmethod
    def skeletal_muscle_percentage(self) -> float:
        """Skeletal muscle as a percentage of total weight."""

    @property
    @abc.abstractmethod
    def muscle_mass(self) -> float:
        """Muscle mass in kg (fat-free mass excluding bone)."""

    @property
    @abc.abstractmethod
    def bone_mass(self) -> float:
        """Total mass of the bones, in kg."""

    @property
    @abc.abstractmethod
    def protein_percentage(self) -> float:
        """Protein as a percentage of total body weight."""

    @property
    @abc.abstractmethod
    def metabolic_age(self) -> int:
        """Estimate of the body's metabolic age, in years."""

    def as_dict(self) -> dict[str, int | float]:
        """Return every calculated metric, keyed by its property name.

        Only the calculated metrics are included. The constructor inputs
        (weight, height, age, sex, impedance, athlete) are not metrics and
        are deliberately left out, as are private intermediates.

        Because implementations expose different metrics, the set of keys
        depends on which one produced it.

        Returns:
            dict: Metric name -> value, for every metric this class exposes.
        """
        return {
            name: getattr(self, name)
            for name in dir(type(self))
            if not name.startswith("_")
            and isinstance(getattr(type(self), name, None), cached_property)
        }


class BodyMetrics(BaseBodyMetrics):
    """Class for calculating various body composition metrics based on weight, height, age, sex, and impedance.

    Closely matches the algorithm the VeSync app pairs with the ESF-551, FIT-8S, EFS-A591S and ESF-24.
    It is *not* the algorithm used for the EFS-C651, which differs materially
    (see BodyMetricsV2).
    """

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

        bfp = (
            age_factor[self.sex] * self.age
            + bmi_factor[self.sex] * self.body_mass_index
            - 500 / self.impedance
            - constant[self.sex]
        )
        if self.athlete:
            base_divisor = [3.5, 3.0]
            bmi_divisor = [3.0, 2.4]
            bfp = (
                bfp / base_divisor[self.sex]
                + self.body_mass_index / bmi_divisor[self.sex]
            )

        return max(5, min(75, floor(bfp * 10) / 10))

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
        return round(
            bfp_factor[self.sex] * self.body_fat_percentage
            - vfv_factor[self.sex] * self.visceral_fat_value,
            1,
        )

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
        vfv = int(
            bmi_factor[self.sex] * self.body_mass_index
            + bfp_factor[self.sex] * self.body_fat_percentage
            + fat_factor[self.sex] * (self.weight - self.fat_free_weight)
            - constant[self.sex]
        )
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
        bwp = round(
            ff2_factor[self.sex] * (self.fat_free_weight - ff1) / self.weight * 100, 1
        )
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
        return round(
            ff2_factor[self.sex] * (self.fat_free_weight - ff1) / self.weight * 100, 1
        )

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
        bpp = round(
            100
            - bfp_factor[self.sex] * self.body_fat_percentage
            - self.bone_mass / self.weight * 100
            - self.body_water_percentage,
            1,
        )
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
        res = factor[self.sex] * (
            height_factor[self.sex] * self.height - constant[self.sex]
        )
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
            return int(
                100
                - 50
                * (self.body_fat_percentage - constant[self.sex])
                / (45 - constant[self.sex])
            )
        return int(
            100
            - 50
            * (constant[self.sex] - self.body_fat_percentage)
            / (constant[self.sex] - 5)
        )

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


def _func1(value: float, factor: float) -> int:
    """Scale and round half-up to an integer, as the algorithm does throughout."""
    return int(value * factor + 0.5)


def _rate2kg(rate: int, weight_dg: int) -> int:
    """Tenths of a percent -> tenths of a kg, truncating."""
    return rate * weight_dg // 1000


def _kg2rate(mass_dg: int, weight_dg: int) -> int:
    """Tenths of a kg -> tenths of a percent, truncating."""
    return mass_dg * 1000 // weight_dg


class BodyMetricsV2(BaseBodyMetrics):
    """Class for calculating various body composition metrics based on weight, height, age, sex, and impedance.
    Closely matches the algorithm the VeSync app pairs with the EFS-C651.
    """

    @cached_property
    def _raw(self) -> dict[str, int]:
        """Every metric in the algorithm's own fixed-point units.

        Masses are tenths of a kg, rates are tenths of a percent; the visceral
        index, BMR and body age are plain integers.
        """
        w = int(self.weight * 10)
        h = round(self.height * 100)
        z = self.impedance
        male = self.sex == Sex.Male
        weight_kg = w / 10

        # --- lean body mass, and body fat as the remainder ---
        lbm_raw = (
            12.226
            + 9.058 * (h / 100.0) ** 2
            + 0.032 * w
            - 0.0068 * z
            - 0.0542 * self.age
        )
        lbm = lbm_raw - (0.8 if male else (9.25 if self.age < 50 else 7.25))
        if male:
            # Applied twice, deliberately.
            if w < 610:
                lbm *= 0.98
            if w < 610:
                lbm *= 0.98
        else:
            if w < 500:
                lbm *= 1.02
            if w > 600:
                lbm *= 0.96
            if h > 160:
                lbm *= 1.03

        fat_mass = weight_kg - lbm
        if self.athlete:
            fat_mass = 0.778 * fat_mass - 0.93 if male else 0.992 * fat_mass - 1.5
        fat_rate = max(50, min(750, int(fat_mass * 10000 / w)))

        bmi = round(weight_kg / ((h / 100.0) ** 2) * 10)
        fat_kg = _rate2kg(fat_rate, w)
        ffm = w - fat_kg

        # --- bone, and muscle as what is left of fat-free mass ---
        bone = int(0.5158 * lbm_raw - (1.802 if male else 2.4569))
        bone = bone + 1 if bone > 22 else bone - 1
        if self.athlete:
            bone += 1 if bone < 20 else (2 if bone < 30 else 3)

        muscle = ffm - bone
        muscle_rate = _kg2rate(muscle, w)

        # --- water, and skeletal muscle and protein derived from it ---
        water_rate = (1000 - fat_rate) * 7 // 10
        water_rate = _func1(water_rate, 0.98 if water_rate > 500 else 1.02)
        if self.athlete:
            water_rate = _func1(water_rate, 0.996 if male else 0.985) + 4
        water_rate = max(350, water_rate)

        water_kg = _rate2kg(water_rate, w)
        skeletal_kg = int(0.832 * water_kg - 27.354)
        protein_rate = max(
            20, min(300, _kg2rate(int(_func1(water_kg, 0.275) - 1.36), w))
        )

        # --- basal metabolic rate ---
        if male:
            bmr = _func1(w, 1.4916) + 878 - _func1(h, 0.726) - _func1(self.age, 8.976)
        else:
            bmr = _func1(w, 1.0204) + 865 - _func1(h, 0.3934) - _func1(self.age, 6.204)
        if self.athlete:
            bmr = int(1.16 * bmr - 149)
        bmr = max(500, bmr)

        # --- body age, blended from two BMI-driven estimates ---
        a1 = int(self.age + 28.428 - 0.1428 * bmi)
        a1 = max(self.age - 5, min(self.age + 5, a1))
        a2 = int(self.age + 0.1724 * bmi - 34.931)
        a2 = max(self.age - 8, min(self.age + 8, a2))
        body_age = max(6, min(99, int(0.4 * a1 + 0.6 * a2)))

        # --- visceral fat, on a different curve above and below a
        # --- height-for-weight threshold
        if male:
            if h >= 0.16 * w + 63:
                vfal = (-0.0015 * h + 0.765) * w / 10 - 0.143 * h + 0.15 * self.age - 5
            else:
                vfal = 30.5 * w / (0.0826 * h**2 - 0.4 * h + 48) - 2.9 + 0.15 * self.age
        else:
            if w <= 5 * h - 130:
                vfal = (
                    (-0.0024 * h + 0.691) * w / 10 - 0.027 * h + 0.07 * self.age - 10.5
                )
            else:
                vfal = 50 * w / (0.1158 * h**2 + 1.45 * h - 120) - 6 + 0.07 * self.age
        if self.athlete:
            if vfal < 2:
                vfal = 1.0
            elif vfal < 10:
                vfal -= 2
            elif vfal < 20:
                vfal *= 0.8
            else:
                vfal *= 0.85
        vfal = max(1, min(50, int(vfal)))

        # --- subcutaneous fat ---
        subcut_index = max(
            10, min(300, int(0.031 * z + 0.94 * bmi + 1.049 * self.age - 210.772))
        )
        subcut_kg = fat_kg - 9.4 * subcut_index / 34
        if self.athlete:
            subcut_kg *= 0.85
        subcut_rate = max(10, min(600, int(1000 * subcut_kg / w)))

        return {
            "bmi": bmi,
            "fat_rate": fat_rate,
            "fat_kg": fat_kg,
            "ffm": ffm,
            "bone": bone,
            "muscle": muscle,
            "muscle_rate": muscle_rate,
            "water_rate": water_rate,
            "skeletal_kg": skeletal_kg,
            "protein_rate": protein_rate,
            "bmr": bmr,
            "body_age": body_age,
            "vfal": vfal,
            "subcut_rate": subcut_rate,
        }

    @cached_property
    def body_mass_index(self) -> float:
        """Body Mass Index (BMI), to 0.1."""
        return self._raw["bmi"] / 10

    @cached_property
    def body_fat_percentage(self) -> float:
        """Body fat as a percentage of total mass, clamped to [5, 75]."""
        return self._raw["fat_rate"] / 10

    @cached_property
    def body_fat_mass(self) -> float:
        """Body fat in kg. Specific to this algorithm."""
        return self._raw["fat_kg"] / 10

    @cached_property
    def fat_free_weight(self) -> float:
        """Total weight minus body fat, in kg."""
        return self._raw["ffm"] / 10

    @cached_property
    def subcutaneous_fat_percentage(self) -> float:
        """Fat just beneath the skin, as a percentage of total weight."""
        return self._raw["subcut_rate"] / 10

    @cached_property
    def visceral_fat_value(self) -> int:
        """Visceral fat index, between 1 and 50.

        Note the range differs from :class:`BodyMetrics`, which reports 1-30.
        """
        return self._raw["vfal"]

    @cached_property
    def body_water_percentage(self) -> float:
        """Total body water as a percentage of total weight."""
        return self._raw["water_rate"] / 10

    @cached_property
    def basal_metabolic_rate(self) -> int:
        """Calories required at rest, with a floor of 500."""
        return self._raw["bmr"]

    @cached_property
    def skeletal_muscle_percentage(self) -> float:
        """Skeletal muscle as a percentage of total weight.

        This algorithm computes skeletal muscle as a mass; the percentage is
        derived from it, which is what the vendor app displays too.
        """
        return round(self.skeletal_muscle_mass / self.weight * 100, 1)

    @cached_property
    def skeletal_muscle_mass(self) -> float:
        """Skeletal muscle in kg. Specific to this algorithm."""
        return self._raw["skeletal_kg"] / 10

    @cached_property
    def muscle_mass(self) -> float:
        """Muscle mass in kg (fat-free mass excluding bone)."""
        return self._raw["muscle"] / 10

    @cached_property
    def muscle_percentage(self) -> float:
        """Muscle mass as a percentage of total weight.

        Computed directly by the algorithm, which truncates; the vendor app
        displays a rounded figure instead, so this can read 0.1 lower than
        the app for the same measurement.
        """
        return self._raw["muscle_rate"] / 10

    @cached_property
    def bone_mass(self) -> float:
        """Total bone mass in kg."""
        return self._raw["bone"] / 10

    @cached_property
    def protein_percentage(self) -> float:
        """Protein as a percentage of total body weight."""
        return self._raw["protein_rate"] / 10

    @cached_property
    def metabolic_age(self) -> int:
        """Metabolic age in years, between 6 and 99."""
        return self._raw["body_age"]


def calc_age(birthdate: date) -> int:
    """
    Calculate age in years as of today, the way the scale's app counts it.

    Full years only: someone whose birthday has not yet occurred this year
    counts as a year younger. Handy for the `age` argument of `BodyMetrics`.

    Args:
        birthdate: The person's date of birth.

    Returns:
        int: Age in whole years.
    """
    today = date.today()
    years = today.year - birthdate.year
    if today.month < birthdate.month or (
        today.month == birthdate.month and today.day < birthdate.day
    ):
        years -= 1
    return years
