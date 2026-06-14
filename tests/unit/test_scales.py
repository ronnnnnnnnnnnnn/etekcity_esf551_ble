"""Unit tests for scale classes."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from bleak.backends.device import BLEDevice

from src.etekcity_esf551_ble import (
    ESF24Scale,
    ESF551Scale,
    EtekcitySmartFitnessScale,
    FIT8SScale,
    WeightUnit,
)

# weight 70.5 kg + impedance 500 ohms, MAC "A9:89:5D:ED:A0:63" (LE), stable, unit=LB.
_FIT8S_ADDRESS = "A9:89:5D:ED:A0:63"
_FIT8S_STABLE_LB = bytes(
    b"\x01\x63\xa0\xed\x5d\x89\xa9\x00\x00\x00\x64\x13\x01\xf4\x01\x01\x01\x00\x00\x00"
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
async def test_fit8s_scale_initialization():
    """FIT8S is an advertisement-based scale sharing the common base class."""
    callback = Mock()
    scale = FIT8SScale(_FIT8S_ADDRESS, callback, bleak_scanner_backend=Mock())

    assert scale.address == _FIT8S_ADDRESS
    assert scale._notification_callback == callback
    assert isinstance(scale, EtekcitySmartFitnessScale)
    # No GATT machinery on advertisement-based scales.
    assert not hasattr(scale, "_cooldown_seconds")


@pytest.mark.asyncio
async def test_fit8s_advertisement_callback_emits_scale_data():
    """A stable FIT8S advertisement is parsed and delivered to the callback."""
    callback = Mock()
    scale = FIT8SScale(_FIT8S_ADDRESS, callback, bleak_scanner_backend=Mock())

    ble_device = Mock(spec=BLEDevice)
    ble_device.address = _FIT8S_ADDRESS
    ble_device.name = "Fit 8S"

    advertisement_data = Mock()
    advertisement_data.manufacturer_data = {0x1234: _FIT8S_STABLE_LB}

    await scale._advertisement_callback(ble_device, advertisement_data)

    callback.assert_called_once()
    scale_data = callback.call_args[0][0]
    assert scale_data.measurements["weight"] == 70.5
    assert scale_data.measurements["impedance"] == 500
    # display_unit comes from the advertisement and is not left in measurements.
    assert scale_data.display_unit == WeightUnit.LB
    assert "display_unit" not in scale_data.measurements
    assert scale.display_unit == WeightUnit.LB
    assert scale_data.name == "Fit 8S"
    assert scale_data.address == _FIT8S_ADDRESS


@pytest.mark.asyncio
async def test_fit8s_advertisement_callback_ignores_other_devices():
    """Advertisements from a different address are ignored."""
    callback = Mock()
    scale = FIT8SScale(_FIT8S_ADDRESS, callback, bleak_scanner_backend=Mock())

    ble_device = Mock(spec=BLEDevice)
    ble_device.address = "00:11:22:33:44:55"
    ble_device.name = "Other"

    advertisement_data = Mock()
    advertisement_data.manufacturer_data = {0x1234: _FIT8S_STABLE_LB}

    await scale._advertisement_callback(ble_device, advertisement_data)
    callback.assert_not_called()


@pytest.mark.asyncio
async def test_fit8s_display_unit_is_observed_not_settable():
    """display_unit can't be commanded on FIT8S; it reflects the advertisement."""
    logger = Mock()
    callback = Mock()
    # A requested unit at construction is ignored (and logged), not stored.
    scale = FIT8SScale(
        _FIT8S_ADDRESS,
        callback,
        WeightUnit.KG,
        bleak_scanner_backend=Mock(),
        logger=logger,
    )
    assert scale.display_unit is None
    assert logger.debug.called

    # After a reading, the getter reflects the unit observed in the advert (LB).
    ble_device = Mock(spec=BLEDevice)
    ble_device.address = _FIT8S_ADDRESS
    ble_device.name = "Fit 8S"
    advertisement_data = Mock()
    advertisement_data.manufacturer_data = {0x1234: _FIT8S_STABLE_LB}
    await scale._advertisement_callback(ble_device, advertisement_data)
    assert scale.display_unit == WeightUnit.LB

    # A later set is still ignored; the observed unit stands.
    logger.debug.reset_mock()
    scale.display_unit = WeightUnit.ST
    assert scale.display_unit == WeightUnit.LB
    assert logger.debug.called


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
