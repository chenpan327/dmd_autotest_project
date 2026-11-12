"""
Radio protocol latency tests (pytest + Allure).

Usage::

    pytest script/test_radio_latency.py -v --alluredir=allure-results
    allure serve allure-results
"""

from __future__ import annotations

import statistics
import time
from typing import List

import allure
import pytest

from src.Protocol.radio.radio_config import RadioConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rc(radio_cfg: dict) -> RadioConfig:
    """Connect once for the whole test module, disconnect when done."""
    port = radio_cfg["radio_serial_port"]
    baud = radio_cfg["radio_serial_baudrate"]
    with allure.step(f"Connect to {port} @ {baud}"):
        r = RadioConfig()
        r.connect(port, baud)
        addr = hex(r._rtp.device_address) if r._rtp.device_address else "unknown"
        allure.attach(addr, "device_address", allure.attachment_type.TEXT)
    yield r
    with allure.step("Disconnect"):
        r.disconnect()


@pytest.fixture(scope="module")
def device_info(rc: RadioConfig) -> dict:
    with allure.step("Query firmware version"):
        ver = rc.get_firmware_version()
        info = {"address": hex(rc._rtp.device_address), "version": ver}
        allure.attach(f"{info}", "device_info", allure.attachment_type.JSON)
    return info


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _measure_and_report(rc: RadioConfig, fn, repeat: int, label: str,
                        max_mean_ms: int) -> List[float]:
    """Measure RTT *repeat* times, attach stats to Allure, assert limit."""
    times_ms: List[float] = []
    for i in range(repeat):
        t0 = time.perf_counter()
        fn(rc)
        elapsed = (time.perf_counter() - t0) * 1000
        times_ms.append(elapsed)
        print(f"  {label} [{i+1:2d}/{repeat}]  {elapsed:6.1f} ms")

    assert len(times_ms) > 0, f"{label}: no samples"
    mean = statistics.mean(times_ms)
    median = statistics.median(times_ms)
    stdev = statistics.stdev(times_ms) if len(times_ms) > 1 else 0
    mn, mx = min(times_ms), max(times_ms)

    # Attach summary to Allure
    summary = (
        f"samples  = {len(times_ms)}\n"
        f"min      = {mn:.1f} ms\n"
        f"max      = {mx:.1f} ms\n"
        f"mean     = {mean:.1f} ms\n"
        f"median   = {median:.1f} ms\n"
        f"stdev    = {stdev:.1f} ms\n"
    )
    allure.attach(summary, f"{label} statistics", allure.attachment_type.TEXT)
    allure.attach(
        "\n".join(f"{v:.1f}" for v in times_ms),
        f"{label} raw data",
        allure.attachment_type.CSV,
    )

    print(f"\n  {label}: n={len(times_ms)} min={mn:.1f} max={mx:.1f} "
          f"mean={mean:.1f} median={median:.1f} stdev={stdev:.1f} ms")

    assert mean < max_mean_ms, (
        f"{label}: mean RTT {mean:.1f} ms exceeds limit {max_mean_ms} ms"
    )
    return times_ms


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@allure.feature("DAV Radio Protocol")
class TestConnect:
    """Connection and basic device info."""

    @allure.story("Connection")
    @allure.severity(allure.severity_level.BLOCKER)
    def test_connected(self, rc: RadioConfig, device_info: dict) -> None:
        """Verify serial port is open and device is discovered."""
        assert rc.is_connected

    @allure.story("Connection")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_firmware_version(self, device_info: dict) -> None:
        """Verify firmware version string is non-empty."""
        assert device_info["version"]


@allure.feature("DAV Radio Protocol")
class TestHeartbeat:
    """Test 1: heartbeat query round-trip time."""

    @allure.story("Heartbeat Query")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.title("Heartbeat RTT")
    @allure.description(
        "Send ASK_HEARTBEAT (0x000E), measure time until "
        "SEND_RADIO_R2_HEARTBEAT (0x0204) is received."
    )
    def test_heartbeat_rtt(self, rc: RadioConfig, radio_cfg: dict) -> None:
        repeat = radio_cfg.get("radio_latency_repeat", 20)
        with allure.step(f"Send ASK_HEARTBEAT ×{repeat}, measure RTT"):
            _measure_and_report(
                rc, lambda r: r.get_heartbeat(), repeat,
                "heartbeat", max_mean_ms=500,
            )


@allure.feature("DAV Radio Protocol")
class TestEncryptKey:
    """Test 2: encrypt key query round-trip time."""

    @allure.story("Encrypt Key Query")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.title("Encrypt Key RTT")
    @allure.description(
        "Send ASK_RADIO_ENCRYPT_KEY (0x0103), measure time until "
        "SEND_RADIO_ENCRYPT_KEY (0x0104) is received."
    )
    def test_encrypt_key_rtt(self, rc: RadioConfig, radio_cfg: dict) -> None:
        repeat = radio_cfg.get("radio_latency_repeat", 20)
        with allure.step(f"Send ASK_RADIO_ENCRYPT_KEY ×{repeat}, measure RTT"):
            _measure_and_report(
                rc, lambda r: r.get_radio_encrypt_key(), repeat,
                "encrypt", max_mean_ms=500,
            )


@allure.feature("DAV Radio Protocol")
class TestButtonSet:
    """Test 3: button param set round-trip time."""

    @allure.story("Button Param Set")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.title("Button Set RTT")
    @allure.description(
        "Send SET_RADIO_BUTTON_PARAM (0x0205), measure time until ACK received."
    )
    def test_button_set_rtt(self, rc: RadioConfig, radio_cfg: dict) -> None:
        repeat = radio_cfg.get("radio_latency_repeat", 20)
        with allure.step(f"Send SET_RADIO_BUTTON_PARAM ×{repeat}, measure RTT"):
            _measure_and_report(
                rc, lambda r: r.set_button_param(long_click_mode=[1, 1]),
                repeat, "button", max_mean_ms=500,
            )


@allure.feature("DAV Radio Protocol")
class TestCombined:
    """Test 4: combined load — heartbeat 1/s + button set 1/s."""

    @allure.story("Combined Load")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.title("Combined load")
    @allure.description(
        "Run heartbeat query at 1 Hz AND button param set at 1 Hz "
        "simultaneously. Verify all responses "
        "arrive and mean RTT stays under 800 ms."
    )
    def test_combined(self, rc: RadioConfig, radio_cfg: dict) -> None:
        combined_duration = radio_cfg.get("radio_latency_combined_duration", 20)
        hb_times: List[float] = []
        btn_times: List[float] = []

        with allure.step(f"Combined load: heartbeat ×1/s + button ×1/s "
                         f"for {combined_duration}s"):
            deadline = time.monotonic() + combined_duration
            hb_next = time.monotonic()
            btn_next = time.monotonic() + 0.5

            while time.monotonic() < deadline:
                now = time.monotonic()
                if now >= hb_next:
                    t0 = time.perf_counter()
                    rc.get_heartbeat()
                    hb_times.append((time.perf_counter() - t0) * 1000)
                    hb_next += 1.0
                    print(f"  HB [{len(hb_times):2d}]  {hb_times[-1]:6.1f} ms")

                now = time.monotonic()
                if now >= btn_next:
                    t0 = time.perf_counter()
                    rc.set_button_param(long_click_mode=[1, 1])
                    btn_times.append((time.perf_counter() - t0) * 1000)
                    btn_next += 1.0
                    print(f"  BTN[{len(btn_times):2d}]  {btn_times[-1]:6.1f} ms")

                time.sleep(0.01)

        _measure_and_report.__wrapped__ = None  # skip; we report manually below

        # Report heartbeat
        if hb_times:
            mean_hb = statistics.mean(hb_times)
            allure.attach(
                f"samples={len(hb_times)} min={min(hb_times):.1f} "
                f"max={max(hb_times):.1f} mean={mean_hb:.1f} "
                f"median={statistics.median(hb_times):.1f} "
                f"stdev={statistics.stdev(hb_times):.1f} ms",
                "Combined Heartbeat stats",
                allure.attachment_type.TEXT,
            )
            allure.attach(
                "\n".join(f"{v:.1f}" for v in hb_times),
                "Combined Heartbeat raw data",
                allure.attachment_type.CSV,
            )
            assert mean_hb < 800, f"HB mean too high: {mean_hb:.0f} ms"

        if btn_times:
            mean_btn = statistics.mean(btn_times)
            allure.attach(
                f"samples={len(btn_times)} min={min(btn_times):.1f} "
                f"max={max(btn_times):.1f} mean={mean_btn:.1f} "
                f"median={statistics.median(btn_times):.1f} "
                f"stdev={statistics.stdev(btn_times):.1f} ms",
                "Combined Button stats",
                allure.attachment_type.TEXT,
            )
            allure.attach(
                "\n".join(f"{v:.1f}" for v in btn_times),
                "Combined Button raw data",
                allure.attachment_type.CSV,
            )
            assert mean_btn < 800, f"BTN mean too high: {mean_btn:.0f} ms"

        assert len(hb_times) >= combined_duration - 2, (
            f"Too few heartbeat samples: {len(hb_times)}"
        )
        assert len(btn_times) >= combined_duration - 2, (
            f"Too few button samples: {len(btn_times)}"
        )
