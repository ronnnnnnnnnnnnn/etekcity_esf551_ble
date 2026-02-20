"""Unit tests for scale classes."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from bleak.backends.device import BLEDevice

from src.etekcity_esf551_ble import (
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
    assert scale.display_unit == WeightUnit.KG
    assert scale._state_mask == 0


@pytest.mark.asyncio
async def test_esf551_scale_notification_handler():
    """Test ESF-551 notification handler uses parser output."""
    callback = Mock()
    scale = ESF551Scale("00:11:22:33:44:55", callback)

    test_payload = b"ignored"
    with patch("src.etekcity_esf551_ble.esf551.parser.parse") as mock_parse:
        mock_parse.return_value = {"weight": 70.5, "display_unit": 0}
        scale._notification_handler("char", test_payload, "test_name", "test_address")

    callback.assert_called_once()
    call_args = callback.call_args[0][0]
    assert call_args.measurements["weight"] == 70.5
    assert call_args.display_unit == WeightUnit.KG


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
    """Test ESF-24 display unit enforcement."""
    scale = ESF24Scale("00:11:22:33:44:55", Mock())

    scale.display_unit = WeightUnit.LB
    assert scale.display_unit == WeightUnit.LB

    with pytest.raises(ValueError):
        scale.display_unit = None


@pytest.mark.asyncio
async def test_scale_direct_instantiation():
    """Test direct scale instantiation works for both models."""
    callback = Mock()

    # Mock the scanner to avoid event loop issues
    with patch(
        "src.etekcity_esf551_ble.parser.get_platform_scanner_backend_type"
    ) as mock_get_scanner:
        mock_scanner_class = Mock()
        mock_scanner_instance = Mock()
        mock_scanner_class.return_value = mock_scanner_instance
        mock_get_scanner.return_value = (mock_scanner_class, None)

        # Test ESF551 direct instantiation
        esf551_scale = ESF551Scale("00:11:22:33:44:55", callback)
        assert isinstance(esf551_scale, ESF551Scale)

        # Test ESF24 direct instantiation
        esf24_scale = ESF24Scale("00:11:22:33:44:55", callback)
        assert isinstance(esf24_scale, ESF24Scale)


@pytest.mark.asyncio
async def test_advertisement_callback_cooldown():
    with patch(
        "src.etekcity_esf551_ble.parser.get_platform_scanner_backend_type"
    ) as mock_get_scanner_backend, patch(
        "src.etekcity_esf551_ble.parser.establish_connection"
    ) as mock_establish_connection, patch(
        "src.etekcity_esf551_ble.parser.time.time"
    ) as mock_time:
        mock_scanner = AsyncMock()
        mock_get_scanner_backend.return_value = (
            Mock(return_value=mock_scanner),
            "mock_backend",
        )
        mock_client = AsyncMock()
        mock_client.is_connected = True
        mock_establish_connection.return_value = mock_client

        scale = ESF551Scale(
            "00:11:22:33:44:55",
            Mock(),
            cooldown_seconds=10,
        )
        scale._start_scale_session = AsyncMock()

        ble_device = Mock(spec=BLEDevice)
        ble_device.address = "00:11:22:33:44:55"

        mock_time.return_value = 100
        await scale._advertisement_callback(ble_device, Mock())
        mock_establish_connection.assert_called_once()

        scale._unavailable_callback(mock_client)
        assert scale._cooldown_end_time == 110

        mock_establish_connection.reset_mock()

        mock_time.return_value = 105
        await scale._advertisement_callback(ble_device, Mock())
        mock_establish_connection.assert_not_called()

        mock_time.return_value = 111
        await scale._advertisement_callback(ble_device, Mock())
        mock_establish_connection.assert_called_once()
