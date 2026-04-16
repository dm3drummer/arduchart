"""MAVLink communication -- parameter flash/read, mission/rally/fence upload."""

from __future__ import annotations

import time
from typing import Any, Callable

from .utils import norm_value, DEFAULT_BAUD

try:
    from pymavlink import mavutil
    HAS_MAVLINK = True
except ImportError:
    HAS_MAVLINK = False


def require_mavlink() -> None:
    """Raise ImportError if pymavlink is not available."""
    if not HAS_MAVLINK:
        raise ImportError("pymavlink required. Install: pip install pymavlink")


class MAVLinkConnection:
    """MAVLink connection for reading/writing flight controller parameters."""

    def __init__(
        self, port: str, baud: int = DEFAULT_BAUD, timeout: int = 30
    ) -> None:
        require_mavlink()
        print(f"Connecting to {port} @ {baud}...")
        self.conn = mavutil.mavlink_connection(port, baud=baud)
        self.conn.wait_heartbeat(timeout=timeout)
        print(
            f"Connected (system {self.conn.target_system}, "
            f"component {self.conn.target_component})"
        )

    def read_all_params(
        self,
        on_progress: Callable[[int, int | None], None] | None = None,
    ) -> dict[str, Any]:
        """Read all parameters from the flight controller.

        Args:
            on_progress: Optional callback(received, total) called as
                         params arrive.  *total* is ``None`` until the
                         first PARAM_VALUE message reports ``param_count``.
        """
        self.conn.mav.param_request_list_send(
            self.conn.target_system, self.conn.target_component
        )
        params: dict[str, Any] = {}
        expected_count: int | None = None
        last_recv = time.time()

        while True:
            msg = self.conn.recv_match(
                type="PARAM_VALUE", blocking=True, timeout=5
            )
            if msg is None:
                if time.time() - last_recv > 10:
                    break
                continue

            last_recv = time.time()
            name = msg.param_id.rstrip("\x00")
            params[name] = norm_value(msg.param_value)

            if expected_count is None:
                expected_count = msg.param_count

            if on_progress is not None:
                on_progress(len(params), expected_count)

            if expected_count and len(params) >= expected_count:
                break
            if len(params) % 100 == 0:
                print(f"  Reading... {len(params)}/{expected_count or '?'}")

        print(f"Read {len(params)} parameters")
        return params

    def write_param(self, name: str, value: float) -> bool:
        """Write a single param to the FC. Returns True on ACK."""
        self.conn.mav.param_set_send(
            self.conn.target_system,
            self.conn.target_component,
            name.encode("utf-8"),
            float(value),
            mavutil.mavlink.MAV_PARAM_TYPE_REAL32,
        )
        msg = self.conn.recv_match(type="PARAM_VALUE", blocking=True, timeout=5)
        return bool(msg and msg.param_id.rstrip("\x00") == name)

    def flash_params(
        self, params: dict[str, Any], dry_run: bool = False
    ) -> list[str]:
        """Write params to FC. Returns list of failed param names."""
        total = len(params)
        success = 0
        failed: list[str] = []

        for i, (key, value) in enumerate(params.items(), 1):
            if dry_run:
                print(f"  [{i}/{total}] Would set {key} = {value}")
                success += 1
                continue
            print(f"  [{i}/{total}] {key} = {value}...", end=" ")
            if self.write_param(key, value):
                print("OK")
                success += 1
            else:
                print("FAILED")
                failed.append(key)

        print(f"\n{success}/{total} parameters written")
        if failed:
            print(f"Failed: {', '.join(failed)}")
        return failed

    def get_sys_status(self) -> dict[str, Any] | None:
        """Request SYS_STATUS for battery and sensor health."""
        msg = self.conn.recv_match(type="SYS_STATUS", blocking=True, timeout=10)
        if msg is None:
            return None
        return {
            "voltage": msg.voltage_battery,
            "current": msg.current_battery,
            "remaining": msg.battery_remaining,
            "present": msg.onboard_control_sensors_present,
            "enabled": msg.onboard_control_sensors_enabled,
            "health": msg.onboard_control_sensors_health,
        }

    def close(self) -> None:
        """Close the MAVLink connection."""
        self.conn.close()

    def __enter__(self) -> MAVLinkConnection:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
