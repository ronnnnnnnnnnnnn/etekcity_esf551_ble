"""Integration tests for the complete scale workflow."""

from datetime import date
from unittest.mock import Mock, patch

import pytest

from src.etekcity_esf551_ble import ESF24Scale, ESF551Scale
from src.etekcity_esf551_ble.esf551.body_metrics import EtekcitySmartFitnessScaleWithBodyMetrics, Sex


@pytest.mark.asyncio
async def test_esf551_full_workflow():
    """Test complete ESF-551 workflow including body metrics."""
    callback = Mock()

    # Mock the scanner to avoid event loop issues
    with patch("src.etekcity_esf551_ble.parser.get_platform_scanner_backend_type") as mock_get_scanner:
        mock_scanner_class = Mock()
        mock_scanner_instance = Mock()
        mock_scanner_class.return_value = mock_scanner_instance
        mock_get_scanner.return_value = mock_scanner_class

        # Test ESF-551 scale
        scale = ESF551Scale("00:11:22:33:44:55", callback)

        # Mock the _parse_payload method to return test data
        test_data = {
            "weight": 75.5,
            "impedance": 500,
            "display_unit": 0  # KG
        }
        scale._parse_payload = Mock(return_value=test_data)
        scale._weight_characteristic_uuid = Mock(return_value="test-uuid")

        # Test notification handling
        scale._notification_handler("char", b"test_data", "test_name", "test_address")
        callback.assert_called_once()

        # Verify the callback received the correct data
        call_args = callback.call_args[0][0]
        assert call_args.measurements["weight"] == 75.5
        assert call_args.measurements["impedance"] == 500
        assert call_args.display_unit.value == 0


@pytest.mark.asyncio
async def test_esf24_kg_only_workflow():
    """Test ESF-24 workflow with kg-only restriction."""
    callback = Mock()

    # Mock the scanner to avoid event loop issues
    with patch("src.etekcity_esf551_ble.parser.get_platform_scanner_backend_type") as mock_get_scanner:
        mock_scanner_class = Mock()
        mock_scanner_instance = Mock()
        mock_scanner_class.return_value = mock_scanner_instance
        mock_get_scanner.return_value = mock_scanner_class

        # Test ESF-24 scale
        scale = ESF24Scale("00:11:22:33:44:55", callback)

        # Mock the _parse_payload method to return test data
        test_data = {
            "weight": 68.2,
            "display_unit": 1  # LB in payload
        }
        scale._parse_payload = Mock(return_value=test_data)
        scale._weight_characteristic_uuid = Mock(return_value="test-uuid")

        # Test notification handling
        scale._notification_handler("char", b"test_data", "test_name", "test_address")
        callback.assert_called_once()

        # Verify the callback received kg data (ESF-24 forces kg)
        call_args = callback.call_args[0][0]
        assert call_args.measurements["weight"] == 68.2
        assert call_args.display_unit.value == 0  # KG


@pytest.mark.asyncio
async def test_body_metrics_integration():
    """Test body metrics integration with ESF-551 scale."""
    callback = Mock()

    # Mock the scanner to avoid event loop issues
    with patch("src.etekcity_esf551_ble.parser.get_platform_scanner_backend_type") as mock_get_scanner:
        mock_scanner_class = Mock()
        mock_scanner_instance = Mock()
        mock_scanner_class.return_value = mock_scanner_instance
        mock_get_scanner.return_value = mock_scanner_class

        # Create body metrics scale
        body_scale = EtekcitySmartFitnessScaleWithBodyMetrics(
            "00:11:22:33:44:55",
            callback,
            Sex.Male,
            date(1990, 1, 1),
            1.75
        )

        # Mock the _parse_payload method to return test data with impedance
        test_data = {
            "weight": 75.0,
            "impedance": 500,
            "display_unit": 0  # KG
        }
        body_scale._parse_payload = Mock(return_value=test_data)
        body_scale._weight_characteristic_uuid = Mock(return_value="test-uuid")

        # Test notification handling
        body_scale._notification_handler("char", b"test_data", "test_name", "test_address")
        callback.assert_called_once()

        # Verify the callback received body metrics data
        call_args = callback.call_args[0][0]
        assert call_args.measurements["weight"] == 75.0
        assert call_args.measurements["impedance"] == 500
        # Should also have body metrics calculated
        assert "body_mass_index" in call_args.measurements
        assert "body_fat_percentage" in call_args.measurements

