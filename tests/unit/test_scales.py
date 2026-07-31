"""Unit tests for scale classes."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from bleak.backends.device import BLEDevice

from src.etekcity_esf551_ble import (
    EFSC651Scale,
    EFSA591SScale,
    ESF24Scale,
    ESF551Scale,
    EtekcitySmartFitnessScale,
    FIT8SScale,
    WeightUnit,
)
from src.etekcity_esf551_ble.efsa591s import protocol as a5

# weight 70.5 kg + impedance 500 ohms, MAC "A9:89:5D:ED:A0:63" (LE), stable, unit=LB.
_FIT8S_ADDRESS = "A9:89:5D:ED:A0:63"
_FIT8S_STABLE_LB = bytes(
    b"\x01\x63\xa0\xed\x5d\x89\xa9\x00\x00\x00\x64\x13\x01\xf4\x01\x01\x01\x00\x00\x00"
)
# Same frame with the stability flag (byte 15) cleared: a settling reading.
_FIT8S_UNSTABLE_LB = _FIT8S_STABLE_LB[:15] + b"\x00" + _FIT8S_STABLE_LB[16:]


def _fit8s_advertisement(payload: bytes):
    """Build a (ble_device, advertisement_data) pair carrying the payload."""
    ble_device = Mock(spec=BLEDevice)
    ble_device.address = _FIT8S_ADDRESS
    ble_device.name = "Fit 8S"
    advertisement_data = Mock()
    advertisement_data.manufacturer_data = {0x1234: payload}
    return ble_device, advertisement_data


@pytest.mark.asyncio
async def test_esf551_scale_initialization():
    """Test ESF-551 scale initialization."""
    callback = Mock()
    scale = ESF551Scale("00:11:22:33:44:55", callback, bleak_scanner_backend=Mock())

    assert scale.address == "00:11:22:33:44:55"
    assert scale._notification_callback == callback
    assert scale._display_unit is None
    assert scale._unit_update_flag is False


@pytest.mark.asyncio
async def test_esf24_scale_initialization():
    """Test ESF-24 scale initialization."""
    callback = Mock()
    scale = ESF24Scale("00:11:22:33:44:55", callback, bleak_scanner_backend=Mock())

    assert scale.address == "00:11:22:33:44:55"
    assert scale._notification_callback == callback
    assert scale.display_unit == WeightUnit.KG
    assert scale._state_mask == 0


@pytest.mark.asyncio
async def test_esf551_scale_notification_handler():
    """Test ESF-551 notification handler uses parser output."""
    callback = Mock()
    scale = ESF551Scale("00:11:22:33:44:55", callback, bleak_scanner_backend=Mock())

    test_payload = b"ignored"
    with patch("src.etekcity_esf551_ble.esf551.scale.parse") as mock_parse:
        mock_parse.return_value = {"weight": 70.5, "display_unit": 0}
        scale._notification_handler("char", test_payload, "test_name", "test_address")

    callback.assert_called_once()
    call_args = callback.call_args[0][0]
    assert call_args.measurements["weight"] == 70.5
    assert call_args.display_unit == WeightUnit.KG


@pytest.mark.asyncio
async def test_esf551_scale_set_display_unit():
    """Test ESF-551 display unit setting."""
    scale = ESF551Scale("00:11:22:33:44:55", Mock(), bleak_scanner_backend=Mock())

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
async def test_esf24_notification_handler_delivers_weight_and_impedance():
    """A final ESF-24 frame reaches the callback with both impedance bands."""
    callback = Mock()
    scale = ESF24Scale("00:11:22:33:44:55", callback, bleak_scanner_backend=Mock())

    # Capture-verified final frame: 110.80 kg, 363 Ω at 50 kHz, 308 Ω at 500 kHz.
    scale._notification_handler(
        "char", bytearray.fromhex("100b152b4801016b013445"), "QN-Scale1", "test_address"
    )

    callback.assert_called_once()
    scale_data = callback.call_args[0][0]
    assert scale_data.measurements["weight"] == 110.80
    assert scale_data.measurements["impedance"] == 363
    assert scale_data.measurements["impedance_500khz"] == 308
    assert scale_data.display_unit == WeightUnit.KG
    assert scale_data.address == "test_address"


@pytest.mark.asyncio
async def test_esf24_settling_frames_are_logged_once_per_session():
    """A weigh-in streams dozens of settling frames; only the first is announced."""
    callback = Mock()
    logger = Mock()
    scale = ESF24Scale(
        "00:11:22:33:44:55", callback, bleak_scanner_backend=Mock(), logger=logger
    )
    settling = bytearray.fromhex("100b152b4800016b013445")

    for _ in range(5):
        scale._notification_handler("char", settling, "QN-Scale1", "test_address")

    callback.assert_not_called()
    # Announced once, and never as unrecognized: these frames are understood.
    messages = [c.args[0] for c in logger.debug.call_args_list]
    assert sum("settling" in m for m in messages) == 1
    assert not any("unrecognized" in m for m in messages)


@pytest.mark.asyncio
async def test_esf24_unrecognized_payload_is_logged_as_unrecognized():
    """A payload that is not a known frame is still reported as unrecognized."""
    callback = Mock()
    logger = Mock()
    scale = ESF24Scale(
        "00:11:22:33:44:55", callback, bleak_scanner_backend=Mock(), logger=logger
    )

    scale._notification_handler(
        "char", bytearray.fromhex("aabbccdd"), "QN-Scale1", "test_address"
    )

    callback.assert_not_called()
    messages = [c.args[0] for c in logger.debug.call_args_list]
    assert sum("unrecognized" in m for m in messages) == 1


@pytest.mark.asyncio
async def test_esf24_logs_every_received_payload():
    """Every frame is dumped at debug so a weigh-in can be reconstructed."""
    callback = Mock()
    logger = Mock()
    scale = ESF24Scale(
        "00:11:22:33:44:55", callback, bleak_scanner_backend=Mock(), logger=logger
    )

    frames = [
        bytearray.fromhex("100b152b4800016b013445"),  # settling
        bytearray.fromhex("100b152b4801016b013445"),  # final
        bytearray.fromhex("ff0102"),  # not an ESF-24 frame at all
    ]
    for frame in frames:
        scale._notification_handler("char", frame, "QN-Scale1", "test_address")

    rx = [c for c in logger.debug.call_args_list if "RX payload" in c.args[0]]
    assert [c.args[1] for c in rx] == [frame.hex() for frame in frames]


@pytest.mark.asyncio
async def test_injected_logger_receives_model_specific_messages():
    """The logger argument covers model messages, not just base-class ones."""
    logger = Mock()
    scale = ESF24Scale(
        "00:11:22:33:44:55", Mock(), bleak_scanner_backend=Mock(), logger=logger
    )

    scale._notification_handler(
        "char", bytearray.fromhex("ff0102"), "QN-Scale1", "test_address"
    )

    messages = [c.args[0] for c in logger.debug.call_args_list]
    assert any("RX payload" in m for m in messages)
    assert any("unrecognized" in m for m in messages)


def test_default_logger_keeps_each_models_own_module_name():
    """Without an injected logger, models stay on their own logger names."""
    esf24 = ESF24Scale("00:11:22:33:44:55", Mock(), bleak_scanner_backend=Mock())
    esf551 = ESF551Scale("00:11:22:33:44:55", Mock(), bleak_scanner_backend=Mock())
    fit8s = FIT8SScale(_FIT8S_ADDRESS, Mock(), bleak_scanner_backend=Mock())
    efsc651 = EFSC651Scale(
        "CF:E9:06:17:9A:46", Mock(), bleak_scanner_backend=Mock()
    )

    assert esf24._logger.name.endswith("esf24.scale")
    assert esf551._logger.name.endswith("esf551.scale")
    assert fit8s._logger.name.endswith("fit8s.scale")
    assert efsc651._logger.name.endswith("efsc651.scale")


def test_efsc651_emits_captured_weight_and_impedance():
    callback = Mock()
    scale = EFSC651Scale(
        "CF:E9:06:17:9A:46", callback, bleak_scanner_backend=Mock()
    )
    scale._key = b"\x01" * 16
    scale._iv = b"\x02" * 16
    plaintext = bytes.fromhex(
        "32313436363837355f5f5f5f5f5f5f5f5f5f5f5f0000"
        "742101b456bf00454b6c6a0102000002"
    )
    frame = a5.build_frame(1, 0x4422, b"\x00" * 16, a5.CHANNEL_AES)

    with patch(
        "src.etekcity_esf551_ble.efsc651.scale.a5.decrypt_frame_payload",
        return_value=plaintext,
    ):
        scale._handle_frame(frame, "Etekcity Smart Fitness Scale", scale.address)

    callback.assert_called_once()
    scale_data = callback.call_args.args[0]
    assert scale_data.measurements == {"weight": 74.1, "impedance": 517}
    assert scale_data.display_unit == WeightUnit.KG


@pytest.mark.asyncio
async def test_esf24_scale_set_display_unit():
    """Test ESF-24 display unit enforcement."""
    scale = ESF24Scale("00:11:22:33:44:55", Mock(), bleak_scanner_backend=Mock())

    scale.display_unit = WeightUnit.LB
    assert scale.display_unit == WeightUnit.LB

    with pytest.raises(ValueError):
        scale.display_unit = None


@pytest.mark.asyncio
async def test_gatt_models_default_to_a_reconnect_cooldown():
    """GATT scales connect on every advertisement, so they need a window.

    Without one, the stragglers a scale keeps emitting while it spins down
    after a measurement each start a futile connect cycle.
    """
    for cls in (ESF551Scale, ESF24Scale, EFSA591SScale, EFSC651Scale):
        scale = cls("00:11:22:33:44:55", Mock(), bleak_scanner_backend=Mock())
        assert scale._cooldown_seconds == 5, cls.__name__


@pytest.mark.asyncio
async def test_cooldown_default_is_overridable():
    """Callers that know better (e.g. Home Assistant) can widen the window."""
    scale = ESF551Scale(
        "00:11:22:33:44:55", Mock(), bleak_scanner_backend=Mock(), cooldown_seconds=10
    )
    assert scale._cooldown_seconds == 10


@pytest.mark.asyncio
async def test_esf24_write_without_client_is_not_a_warning():
    """Losing the write race with a disconnect is benign, not warning-worthy."""
    logger = Mock()
    scale = ESF24Scale(
        "00:11:22:33:44:55", Mock(), bleak_scanner_backend=Mock(), logger=logger
    )

    await scale._safe_write(bytearray(b"\x00"))

    logger.warning.assert_not_called()
    assert any(
        "no active client" in call.args[0] for call in logger.debug.call_args_list
    )


@pytest.mark.asyncio
async def test_scale_direct_instantiation():
    """Test direct scale instantiation works for both models."""
    callback = Mock()

    # Mock the scanner to avoid event loop issues
    with patch(
        "src.etekcity_esf551_ble.scale.get_platform_scanner_backend_type"
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
    # Model-level dedupe default: the cooldown window outlasts the
    # advertising burst so one weigh-in delivers one callback.
    assert scale._cooldown_seconds == 10
    # No GATT machinery on advertisement-based scales.
    assert not hasattr(scale, "_client")


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
async def test_fit8s_repeated_stable_frames_within_cooldown_deliver_once():
    # A weigh-in re-broadcasts the final frame for the whole advertising
    # burst; delivering a reading arms the cooldown so only one lands.
    callback = Mock()
    scale = FIT8SScale(_FIT8S_ADDRESS, callback, bleak_scanner_backend=Mock())
    ble_device, advertisement_data = _fit8s_advertisement(_FIT8S_STABLE_LB)

    await scale._advertisement_callback(ble_device, advertisement_data)
    await scale._advertisement_callback(ble_device, advertisement_data)

    assert callback.call_count == 1


@pytest.mark.asyncio
async def test_fit8s_stable_frame_after_cooldown_expiry_delivers_again():
    callback = Mock()
    scale = FIT8SScale(_FIT8S_ADDRESS, callback, bleak_scanner_backend=Mock())
    ble_device, advertisement_data = _fit8s_advertisement(_FIT8S_STABLE_LB)

    await scale._advertisement_callback(ble_device, advertisement_data)
    scale._cooldown_end_time = 0  # simulate the window elapsing
    await scale._advertisement_callback(ble_device, advertisement_data)

    assert callback.call_count == 2


@pytest.mark.asyncio
async def test_fit8s_zero_cooldown_delivers_every_stable_frame():
    callback = Mock()
    scale = FIT8SScale(
        _FIT8S_ADDRESS, callback, bleak_scanner_backend=Mock(), cooldown_seconds=0
    )
    ble_device, advertisement_data = _fit8s_advertisement(_FIT8S_STABLE_LB)

    await scale._advertisement_callback(ble_device, advertisement_data)
    await scale._advertisement_callback(ble_device, advertisement_data)

    assert callback.call_count == 2


@pytest.mark.asyncio
async def test_fit8s_unstable_frame_does_not_arm_cooldown():
    callback = Mock()
    scale = FIT8SScale(_FIT8S_ADDRESS, callback, bleak_scanner_backend=Mock())
    ble_device, settling = _fit8s_advertisement(_FIT8S_UNSTABLE_LB)
    _, final = _fit8s_advertisement(_FIT8S_STABLE_LB)

    await scale._advertisement_callback(ble_device, settling)
    await scale._advertisement_callback(ble_device, final)

    assert callback.call_count == 1


@pytest.mark.asyncio
async def test_advertisement_callback_cooldown():
    with (
        patch(
            "src.etekcity_esf551_ble.scale.get_platform_scanner_backend_type"
        ) as mock_get_scanner_backend,
        patch(
            "src.etekcity_esf551_ble.scale.establish_connection"
        ) as mock_establish_connection,
        patch("src.etekcity_esf551_ble.scale.time.time") as mock_time,
    ):
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
