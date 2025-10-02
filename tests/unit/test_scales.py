"""Unit tests for scale classes."""

from unittest.mock import Mock, patch

import pytest

from src.etekcity_esf551_ble import (
    EtekcitySmartFitnessScale,
    ESF24Scale,
    ESF551Scale,
    WeightUnit,
)


@pytest.mark.asyncio
async def test_esf551_scale_initialization():
    """Test ESF-551 scale initialization."""
    callback = Mock()
    scale = ESF551Scale("00:11:22:33:44:55", callback)

    assert scale.address == "00:11:22:33:44:55"
    assert scale._notification_callback == callback
    assert scale._display_unit is None
    assert scale._unit_update_flag is False


@pytest.mark.asyncio
async def test_esf24_scale_initialization():
    """Test ESF-24 scale initialization."""
    callback = Mock()
    scale = ESF24Scale("00:11:22:33:44:55", callback)

    assert scale.address == "00:11:22:33:44:55"
    assert scale._notification_callback == callback
    # ESF24 always uses kg, no unit changes allowed
    assert scale._display_unit == WeightUnit.KG
    assert scale._unit_update_flag is False
    assert scale.display_unit == WeightUnit.KG


@pytest.mark.asyncio
async def test_scale_notification_handler():
    """Test scale notification handler."""
    callback = Mock()
    scale = EtekcitySmartFitnessScale("00:11:22:33:44:55", callback)

    # Mock the abstract methods
    scale._parse_payload = Mock(return_value={"weight": 70.5, "display_unit": 0})
    scale._weight_characteristic_uuid = Mock(return_value="test-uuid")

    # Simulate receiving data
    scale._notification_handler("char", b"test_data", "test_name", "test_address")

    # Check that callback was called
    callback.assert_called_once()


@pytest.mark.asyncio
async def test_esf551_scale_set_display_unit():
    """Test ESF-551 display unit setting."""
    scale = ESF551Scale("00:11:22:33:44:55", Mock())

    # Test setting different units
    scale.display_unit = WeightUnit.KG
    assert scale._display_unit == WeightUnit.KG
    assert scale._unit_update_flag is True

    scale.display_unit = WeightUnit.LB
    assert scale._display_unit == WeightUnit.LB
    assert scale._unit_update_flag is True

    scale.display_unit = WeightUnit.ST
    assert scale._display_unit == WeightUnit.ST
    assert scale._unit_update_flag is True


@pytest.mark.asyncio
async def test_esf24_scale_set_display_unit():
    """Test ESF-24 display unit setting (should be ignored)."""
    scale = ESF24Scale("00:11:22:33:44:55", Mock())

    # ESF24 ignores unit changes - always stays at kg
    scale.display_unit = WeightUnit.LB
    assert scale._display_unit == WeightUnit.KG
    assert scale.display_unit == WeightUnit.KG
    assert scale._unit_update_flag is False


@pytest.mark.asyncio
async def test_scale_direct_instantiation():
    """Test direct scale instantiation works for both models."""
    callback = Mock()

    # Mock the scanner to avoid event loop issues
    with patch("src.etekcity_esf551_ble.parser.get_platform_scanner_backend_type") as mock_get_scanner:
        mock_scanner_class = Mock()
        mock_scanner_instance = Mock()
        mock_scanner_class.return_value = mock_scanner_instance
        mock_get_scanner.return_value = mock_scanner_class

        # Test ESF551 direct instantiation
        esf551_scale = ESF551Scale("00:11:22:33:44:55", callback)
        assert isinstance(esf551_scale, ESF551Scale)

        # Test ESF24 direct instantiation
        esf24_scale = ESF24Scale("00:11:22:33:44:55", callback)
        assert isinstance(esf24_scale, ESF24Scale)

        # Test backward compatibility alias
        legacy_scale = EtekcitySmartFitnessScale("00:11:22:33:44:55", callback)
        assert isinstance(legacy_scale, ESF551Scale)

