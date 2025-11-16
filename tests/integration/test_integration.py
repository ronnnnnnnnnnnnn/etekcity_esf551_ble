"""Integration tests for the complete scale workflow."""

import asyncio
from datetime import date
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.etekcity_esf551_ble import ESF24Scale, ESF551Scale
from src.etekcity_esf551_ble.esf551.body_metrics import ESF551ScaleWithBodyMetrics, Sex


def _mock_scanner():
    mock_scanner_class = Mock()
    mock_scanner_instance = Mock()
    mock_scanner_class.return_value = mock_scanner_instance
    return mock_scanner_class, mock_scanner_instance


@pytest.mark.asyncio
async def test_esf551_full_workflow():
    """Test complete ESF-551 workflow including body metrics."""
    callback = Mock()

    with patch("src.etekcity_esf551_ble.parser.get_platform_scanner_backend_type") as mock_get_scanner, patch(
        "src.etekcity_esf551_ble.esf551.parser.parse"
    ) as mock_parse:
        mock_scanner_class, _ = _mock_scanner()
        mock_get_scanner.return_value = mock_scanner_class
        mock_parse.return_value = {
            "weight": 75.5,
            "impedance": 500,
            "display_unit": 0,
        }

        scale = ESF551Scale("00:11:22:33:44:55", callback)
        scale._notification_handler("char", b"test_data", "test_name", "test_address")

        callback.assert_called_once()
        call_args = callback.call_args[0][0]
        assert call_args.measurements["weight"] == 75.5
        assert call_args.measurements["impedance"] == 500
        assert call_args.display_unit.value == 0


@pytest.mark.asyncio
async def test_esf24_kg_only_workflow():
    """Test ESF-24 workflow with kg-only restriction."""
    callback = Mock()

    with patch("src.etekcity_esf551_ble.parser.get_platform_scanner_backend_type") as mock_get_scanner:
        mock_scanner_class, _ = _mock_scanner()
        mock_get_scanner.return_value = mock_scanner_class

        scale = ESF24Scale("00:11:22:33:44:55", callback)
        weight_payload = bytearray(b"\x10\x0b\x15\x27\x10\x01\x00\x00\x00\x00\x00")

        with patch.object(scale, "_safe_write", AsyncMock(return_value=None)):
            scale._notification_handler("char", weight_payload, "test_name", "test_address")
            await asyncio.sleep(0)

        callback.assert_called_once()
        call_args = callback.call_args[0][0]
        assert call_args.measurements["weight"] == 100.0
        assert call_args.display_unit == scale.display_unit


@pytest.mark.asyncio
async def test_body_metrics_integration():
    """Test body metrics integration with ESF-551 scale."""
    callback = Mock()

    with patch("src.etekcity_esf551_ble.parser.get_platform_scanner_backend_type") as mock_get_scanner, patch(
        "src.etekcity_esf551_ble.esf551.parser.parse"
    ) as mock_parse:
        mock_scanner_class, _ = _mock_scanner()
        mock_get_scanner.return_value = mock_scanner_class

        body_scale = ESF551ScaleWithBodyMetrics(
            "00:11:22:33:44:55",
            callback,
            Sex.Male,
            date(1990, 1, 1),
            1.75,
        )

        mock_parse.return_value = {
            "weight": 75.0,
            "impedance": 500,
            "display_unit": 0,
        }

        body_scale._notification_handler("char", b"test_data", "test_name", "test_address")
        callback.assert_called_once()

        call_args = callback.call_args[0][0]
        assert call_args.measurements["weight"] == 75.0
        assert call_args.measurements["impedance"] == 500
        assert "body_mass_index" in call_args.measurements
        assert "body_fat_percentage" in call_args.measurements
