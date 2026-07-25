"""Unit tests for body metrics calculations."""

from datetime import date
from unittest.mock import patch

from src.etekcity_esf551_ble.body_metrics import BodyMetrics, Sex, calc_age


def test_body_metrics_calculations():
    """Test body metrics calculations work correctly."""
    body_metrics = BodyMetrics(
        weight_kg=75.0, height_m=1.80, age=30, sex=Sex.Male, impedance=500
    )

    assert body_metrics.body_mass_index > 0
    assert body_metrics.body_fat_percentage > 0
    assert body_metrics.body_water_percentage > 0
    assert body_metrics.basal_metabolic_rate > 0
    assert body_metrics.health_score >= 0  # Health score can be 0

    # Check that BMI is reasonable for the inputs
    expected_bmi = 75.0 / (1.80 * 1.80)  # Should be around 23.15
    assert abs(body_metrics.body_mass_index - expected_bmi) < 1.0


def test_body_metrics_different_sex():
    """Test body metrics calculations for different sexes."""
    male_metrics = BodyMetrics(
        weight_kg=70.0, height_m=1.75, age=25, sex=Sex.Male, impedance=550
    )

    female_metrics = BodyMetrics(
        weight_kg=60.0, height_m=1.65, age=25, sex=Sex.Female, impedance=600
    )

    # Different sexes should produce different results
    assert male_metrics.body_fat_percentage != female_metrics.body_fat_percentage
    assert male_metrics.body_water_percentage != female_metrics.body_water_percentage


def test_body_fat_matches_vesync_app_hardware_vectors():
    """Non-athlete body fat matches the VeSync app on real captures."""
    male = BodyMetrics(
        weight_kg=74.50, height_m=1.70, age=43, sex=Sex.Male, impedance=524
    )
    assert male.body_fat_percentage == 20.7

    female = BodyMetrics(
        weight_kg=80.58, height_m=1.75, age=26, sex=Sex.Female, impedance=525
    )
    assert female.body_fat_percentage == 29.5


def test_athlete_body_fat_matches_vesync_app_hardware_vectors():
    """Athlete mode applies the VeSync post-hoc transform, matching the app."""
    male = BodyMetrics(
        weight_kg=74.55,
        height_m=1.70,
        age=43,
        sex=Sex.Male,
        impedance=526,
        athlete=True,
    )
    assert male.body_fat_percentage == 14.5

    female = BodyMetrics(
        weight_kg=80.50,
        height_m=1.75,
        age=26,
        sex=Sex.Female,
        impedance=525,
        athlete=True,
    )
    assert female.body_fat_percentage == 20.7


def test_athlete_mode_cascades_to_downstream_metrics():
    """Downstream metrics derive from the athlete-adjusted body fat."""
    female = BodyMetrics(
        weight_kg=80.50,
        height_m=1.75,
        age=26,
        sex=Sex.Female,
        impedance=525,
        athlete=True,
    )
    # FFW = 80.50 * (1 - 20.7/100) = 63.84; BMR = int(63.84*21.6 + 370)
    assert female.fat_free_weight == 63.84
    assert female.basal_metabolic_rate == 1748

    non_athlete = BodyMetrics(
        weight_kg=80.50, height_m=1.75, age=26, sex=Sex.Female, impedance=525
    )
    assert non_athlete.fat_free_weight < female.fat_free_weight


def test_athlete_body_fat_shares_the_base_lower_clamp():
    """Athlete mode clamps to [5, 75], the same range as the base value.

    The VeSync transform floors at 5.1 instead, but that only binds below
    BMI 11 — far outside any real measurement — so the base clamp is reused.
    """
    lean = BodyMetrics(
        weight_kg=35.65,
        height_m=1.80,
        age=20,
        sex=Sex.Male,
        impedance=800,
        athlete=True,
    )
    assert lean.body_fat_percentage == 5


def test_athlete_defaults_to_false():
    """Omitting the athlete flag keeps the existing non-athlete behavior."""
    default = BodyMetrics(
        weight_kg=74.50, height_m=1.70, age=43, sex=Sex.Male, impedance=524
    )
    explicit = BodyMetrics(
        weight_kg=74.50,
        height_m=1.70,
        age=43,
        sex=Sex.Male,
        impedance=524,
        athlete=False,
    )
    assert default.body_fat_percentage == explicit.body_fat_percentage == 20.7


def test_as_dict_returns_every_computed_metric():
    """as_dict exposes the calculated metrics, keyed by property name."""
    metrics = BodyMetrics(
        weight_kg=74.50, height_m=1.70, age=43, sex=Sex.Male, impedance=524
    )
    as_dict = metrics.as_dict()

    assert as_dict["body_fat_percentage"] == metrics.body_fat_percentage
    assert as_dict["basal_metabolic_rate"] == metrics.basal_metabolic_rate
    assert {
        "body_mass_index",
        "fat_free_weight",
        "body_water_percentage",
        "skeletal_muscle_percentage",
        "muscle_mass",
        "bone_mass",
        "protein_percentage",
        "subcutaneous_fat_percentage",
        "visceral_fat_value",
        "health_score",
        "metabolic_age",
    } <= as_dict.keys()


def test_as_dict_excludes_constructor_inputs():
    """Inputs are not measurements and must not leak into the metrics dict."""
    metrics = BodyMetrics(
        weight_kg=74.50,
        height_m=1.70,
        age=43,
        sex=Sex.Male,
        impedance=524,
        athlete=True,
    )
    assert not {"weight", "height", "age", "sex", "impedance", "athlete"} & (
        metrics.as_dict().keys()
    )


def test_as_dict_reflects_athlete_mode():
    """Athlete mode changes the values, not the set of metrics reported."""
    base = BodyMetrics(74.55, 1.70, 43, Sex.Male, 526).as_dict()
    athlete = BodyMetrics(74.55, 1.70, 43, Sex.Male, 526, athlete=True).as_dict()

    assert athlete["body_fat_percentage"] == 14.5
    assert base["body_fat_percentage"] != athlete["body_fat_percentage"]
    assert base.keys() == athlete.keys()


def test_calc_age_is_birthday_aware():
    """Age counts full years: a birthday still ahead this year is not counted."""
    with patch("src.etekcity_esf551_ble.body_metrics.date") as mock_date:
        mock_date.today.return_value = date(2026, 7, 25)

        assert calc_age(date(1990, 7, 24)) == 36  # birthday already passed
        assert calc_age(date(1990, 7, 25)) == 36  # birthday is today
        assert calc_age(date(1990, 7, 26)) == 35  # birthday still ahead
        assert calc_age(date(1990, 12, 1)) == 35  # later month
        assert calc_age(date(1990, 1, 1)) == 36  # earlier month


def test_body_metrics_edge_cases():
    """Test body metrics with edge case values."""
    # Very low weight
    low_weight_metrics = BodyMetrics(
        weight_kg=40.0, height_m=1.80, age=20, sex=Sex.Male, impedance=800
    )

    # Very high weight
    high_weight_metrics = BodyMetrics(
        weight_kg=150.0, height_m=1.60, age=50, sex=Sex.Female, impedance=300
    )

    # Should still produce reasonable results
    assert low_weight_metrics.body_mass_index > 0
    assert high_weight_metrics.body_mass_index > 0
    assert low_weight_metrics.body_fat_percentage >= 0
    assert high_weight_metrics.body_fat_percentage >= 0
