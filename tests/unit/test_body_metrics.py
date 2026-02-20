"""Unit tests for body metrics calculations."""

from src.etekcity_esf551_ble.esf551.body_metrics import BodyMetrics, Sex


def test_body_metrics_calculations():
    """Test body metrics calculations work correctly."""
    body_metrics = BodyMetrics(
        weight_kg=75.0,
        height_m=1.80,
        age=30,
        sex=Sex.Male,
        impedance=500
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
        weight_kg=70.0,
        height_m=1.75,
        age=25,
        sex=Sex.Male,
        impedance=550
    )

    female_metrics = BodyMetrics(
        weight_kg=60.0,
        height_m=1.65,
        age=25,
        sex=Sex.Female,
        impedance=600
    )

    # Different sexes should produce different results
    assert male_metrics.body_fat_percentage != female_metrics.body_fat_percentage
    assert male_metrics.body_water_percentage != female_metrics.body_water_percentage


def test_body_metrics_edge_cases():
    """Test body metrics with edge case values."""
    # Very low weight
    low_weight_metrics = BodyMetrics(
        weight_kg=40.0,
        height_m=1.80,
        age=20,
        sex=Sex.Male,
        impedance=800
    )

    # Very high weight
    high_weight_metrics = BodyMetrics(
        weight_kg=150.0,
        height_m=1.60,
        age=50,
        sex=Sex.Female,
        impedance=300
    )

    # Should still produce reasonable results
    assert low_weight_metrics.body_mass_index > 0
    assert high_weight_metrics.body_mass_index > 0
    assert low_weight_metrics.body_fat_percentage >= 0
    assert high_weight_metrics.body_fat_percentage >= 0

