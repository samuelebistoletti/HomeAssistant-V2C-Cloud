#!/usr/bin/env python3
"""Live smoke test for the V2C Cloud + Trydan local API.

This script exercises every documented endpoint against a real Trydan
charger and the official V2C Cloud, then **restores every value it
changed**. It is purposefully **not** part of CI — the snapshot/restore
strategy mutates device configuration, which is only safe with explicit
operator consent.

Usage
-----
::

    V2C_CLOUD_API_KEY=<key> V2C_LOCAL_IP=10.35.0.50 \\
        python scripts/live_smoke_test.py --confirm-restore

The ``--confirm-restore`` flag is mandatory: without it the script aborts
with exit code 2 before any HTTP request is sent.

Exit codes
----------
* 0  — all reads/writes succeeded, restore verified
* 1  — at least one assertion failed; check the JSON snapshot for diff
* 2  — invocation guard (missing flag, missing env, etc.)
* 3  — restore phase failed; manual inspection required

Snapshots are written to ``/tmp/v2c_snapshot_<timestamp>.json`` so a
follow-up restore can be attempted manually if the script crashes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import aiohttp

_LOGGER = logging.getLogger("v2c_smoke")
_SNAPSHOT_DIR = Path("/tmp")  # noqa: S108 — intentional, user-controlled host
_CLOUD_BASE = "https://v2c.cloud/kong/v2c_service"
_LOCAL_TIMEOUT = aiohttp.ClientTimeout(total=10)
_CLOUD_TIMEOUT = aiohttp.ClientTimeout(total=20)

# Keys we never touch in write tests because they would isolate the device
# from the operator's network or invalidate cloud auth flows.
_SKIP_WRITE: frozenset[str] = frozenset(
    {"WiFi", "OCPP", "OCPP_ID", "OCPP_ADDR", "InverterIP", "Reboot"}
)


# --------------------------------------------------------------------------- #
# Result accounting                                                            #
# --------------------------------------------------------------------------- #


class Result:
    """Single test outcome with a short label, status and optional detail."""

    def __init__(self, label: str, ok: bool, detail: str = "") -> None:
        """Record a labelled outcome with optional detail string."""
        self.label = label
        self.ok = ok
        self.detail = detail

    def __repr__(self) -> str:
        """Return a compact human-readable representation."""
        status = "OK" if self.ok else "FAIL"
        return f"[{status}] {self.label}{f' — {self.detail}' if self.detail else ''}"


# --------------------------------------------------------------------------- #
# Snapshot / restore                                                           #
# --------------------------------------------------------------------------- #


async def _local_get_json(session: aiohttp.ClientSession, ip: str, path: str) -> Any:
    """GET a JSON-ish payload from the Trydan local HTTP API."""
    async with session.get(f"http://{ip}{path}", timeout=_LOCAL_TIMEOUT) as resp:
        text = (await resp.text()).strip().rstrip("%").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text


async def _local_write(
    session: aiohttp.ClientSession, ip: str, keyword: str, value: str
) -> tuple[int, str]:
    """Issue a write to /write/<keyword>=<value> and return (status, body)."""
    url = f"http://{ip}/write/{keyword}={value}"
    async with session.get(url, timeout=_LOCAL_TIMEOUT) as resp:
        return resp.status, await resp.text()


async def _cloud_request(  # noqa: PLR0913
    session: aiohttp.ClientSession,
    api_key: str,
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    body: Any | None = None,
) -> tuple[int, Any]:
    """Call a cloud endpoint and return (status_code, parsed_body)."""
    url = f"{_CLOUD_BASE}{path}"
    headers = {"apikey": api_key}
    async with session.request(
        method, url, headers=headers, params=params, json=body, timeout=_CLOUD_TIMEOUT
    ) as resp:
        text = await resp.text()
        ctype = resp.headers.get("Content-Type", "")
        if "application/json" in ctype:
            try:
                return resp.status, json.loads(text)
            except json.JSONDecodeError:
                return resp.status, text
        return resp.status, text


async def _snapshot(
    session: aiohttp.ClientSession, ip: str, api_key: str, device_id: str
) -> dict[str, Any]:
    """Capture the device + cloud state we may mutate during the run."""
    realtime = await _local_get_json(session, ip, "/RealTimeData")
    _, pairings = await _cloud_request(session, api_key, "GET", "/pairings/me")
    _, reported = await _cloud_request(
        session, api_key, "GET", "/device/reported", params={"deviceId": device_id}
    )
    _, version = await _cloud_request(
        session, api_key, "GET", "/version", params={"deviceId": device_id}
    )
    _, rfid = await _cloud_request(
        session, api_key, "GET", "/device/rfid", params={"deviceId": device_id}
    )
    snapshot = {
        "captured_at": time.time(),
        "device_id": device_id,
        "local_realtime": realtime,
        "cloud_pairings": pairings,
        "cloud_reported": reported,
        "cloud_version": version,
        "cloud_rfid": rfid,
    }
    out = _SNAPSHOT_DIR / f"v2c_snapshot_{int(time.time())}.json"
    out.write_text(json.dumps(snapshot, indent=2, default=str))
    _LOGGER.info("Snapshot written to %s", out)
    return snapshot


# --------------------------------------------------------------------------- #
# Read phase                                                                   #
# --------------------------------------------------------------------------- #


async def _exercise_reads(
    session: aiohttp.ClientSession, ip: str, api_key: str, device_id: str
) -> list[Result]:
    """Exercise every read-only endpoint we know about."""
    results: list[Result] = []
    # Local API ----------------------------------------------------------------
    try:
        realtime = await _local_get_json(session, ip, "/RealTimeData")
        results.append(
            Result(
                "local /RealTimeData",
                isinstance(realtime, dict) and "ID" in realtime,
                f"keys={sorted(realtime)[:5] if isinstance(realtime, dict) else realtime!r}",
            )
        )
    except (aiohttp.ClientError, TimeoutError) as exc:
        results.append(Result("local /RealTimeData", ok=False, detail=str(exc)))

    # A couple of /read/<keyword> probes
    for kw in ("LogoLED", "LightLED"):
        try:
            value = await _local_get_json(session, ip, f"/read/{kw}")
            results.append(Result(f"local /read/{kw}", ok=True, detail=str(value)))
        except (aiohttp.ClientError, TimeoutError) as exc:
            results.append(Result(f"local /read/{kw}", ok=False, detail=str(exc)))

    # Cloud API ----------------------------------------------------------------
    cloud_reads: tuple[tuple[str, str, dict[str, Any] | None], ...] = (
        ("/pairings/me", "GET", None),
        ("/device/reported", "GET", {"deviceId": device_id}),
        ("/device/currentstatecharge", "POST", {"deviceId": device_id}),
        ("/version", "GET", {"deviceId": device_id}),
        ("/device/rfid", "GET", {"deviceId": device_id}),
        ("/device/connected", "GET", {"deviceId": device_id}),
        ("/device/wifilist", "GET", {"id": device_id}),
        ("/stadistic/device", "GET", {"deviceId": device_id}),
        ("/stadistic/global/me", "GET", None),
        ("/device/personalicepower/all", "GET", {"deviceId": device_id}),
    )
    for path, method, params in cloud_reads:
        try:
            status, _data = await _cloud_request(
                session, api_key, method, path, params=params
            )
            results.append(
                Result(
                    f"cloud {method} {path}",
                    status < 400,
                    f"status={status}",
                )
            )
        except (aiohttp.ClientError, TimeoutError) as exc:
            results.append(Result(f"cloud {method} {path}", ok=False, detail=str(exc)))

    return results


# --------------------------------------------------------------------------- #
# Write phase (no-op writes, then revert verification)                         #
# --------------------------------------------------------------------------- #


async def _exercise_writes(
    session: aiohttp.ClientSession, ip: str, snapshot: dict[str, Any]
) -> list[Result]:
    """Issue safe no-op writes against the LAN /write/ endpoint.

    Every write re-applies the value already present in the snapshot, so a
    correct charger should be unchanged after the run. The verification re-reads
    /RealTimeData and compares the touched keys.
    """
    results: list[Result] = []
    rt = snapshot.get("local_realtime")
    if not isinstance(rt, dict):
        return [Result("local writes pre-check", ok=False, detail="no realtime data")]

    # We probe each writable keyword by re-applying the value already on the
    # device. This is a "round-trip" sanity check, not a behaviour change.
    keywords = (
        "Paused",
        "Locked",
        "Timer",
        "Dynamic",
        "PauseDynamic",
        "Intensity",
        "MinIntensity",
        "MaxIntensity",
        "DynamicPowerMode",
        "ContractedPower",
        "VoltageInstallation",
    )
    for kw in keywords:
        if kw in _SKIP_WRITE:
            continue
        if kw not in rt:
            results.append(
                Result(
                    f"write {kw}", ok=True, detail="absent from RealTimeData; skipped"
                )
            )
            continue
        current = rt[kw]
        value_str = str(int(current)) if isinstance(current, bool) else str(current)
        try:
            status, body = await _local_write(session, ip, kw, value_str)
            results.append(
                Result(
                    f"write {kw}={value_str}",
                    status < 400,
                    f"status={status} body={body[:60]}",
                )
            )
        except (aiohttp.ClientError, TimeoutError) as exc:
            results.append(Result(f"write {kw}", ok=False, detail=str(exc)))

    return results


# --------------------------------------------------------------------------- #
# Restore phase                                                                #
# --------------------------------------------------------------------------- #


async def _restore_and_verify(
    session: aiohttp.ClientSession, ip: str, snapshot: dict[str, Any]
) -> tuple[list[Result], bool]:
    """Re-apply every changed value to the device and verify round-trip."""
    results: list[Result] = []
    rt = snapshot.get("local_realtime")
    if not isinstance(rt, dict):
        return [Result("restore", ok=False, detail="missing snapshot")], False

    keywords = (
        "Paused",
        "Locked",
        "Timer",
        "Dynamic",
        "PauseDynamic",
        "Intensity",
        "MinIntensity",
        "MaxIntensity",
        "DynamicPowerMode",
        "ContractedPower",
        "VoltageInstallation",
    )

    restored_count = 0
    for kw in keywords:
        if kw in _SKIP_WRITE or kw not in rt:
            continue
        original = rt[kw]
        value_str = str(int(original)) if isinstance(original, bool) else str(original)
        try:
            status, _ = await _local_write(session, ip, kw, value_str)
            if status < 400:
                restored_count += 1
        except (aiohttp.ClientError, TimeoutError) as exc:
            results.append(Result(f"restore {kw}", ok=False, detail=str(exc)))

    # Verification re-read
    try:
        final = await _local_get_json(session, ip, "/RealTimeData")
    except (aiohttp.ClientError, TimeoutError) as exc:
        return [
            *results,
            Result("restore verification", ok=False, detail=str(exc)),
        ], False

    diff: dict[str, tuple[Any, Any]] = {}
    if isinstance(final, dict):
        for kw in keywords:
            if kw in rt and rt.get(kw) != final.get(kw):
                diff[kw] = (rt[kw], final.get(kw))

    results.append(
        Result(
            f"restore ({restored_count} keys re-applied)",
            ok=not diff,
            detail=f"diff={diff}" if diff else "all values match",
        )
    )
    return results, not diff


# --------------------------------------------------------------------------- #
# Driver                                                                       #
# --------------------------------------------------------------------------- #


async def _main_async(args: argparse.Namespace) -> int:
    api_key = os.environ.get("V2C_CLOUD_API_KEY", "").strip()
    ip = (args.local_ip or os.environ.get("V2C_LOCAL_IP", "")).strip()
    if not api_key:
        print(
            "ERROR: V2C_CLOUD_API_KEY environment variable is required.",
            file=sys.stderr,
        )
        return 2
    if not ip:
        print(
            "ERROR: V2C_LOCAL_IP environment variable (or --local-ip) is required.",
            file=sys.stderr,
        )
        return 2

    async with aiohttp.ClientSession() as session:
        # Identify device ID via /RealTimeData.
        try:
            rt = await _local_get_json(session, ip, "/RealTimeData")
        except (aiohttp.ClientError, TimeoutError) as exc:
            print(
                f"ERROR: cannot reach local /RealTimeData at {ip}: {exc}",
                file=sys.stderr,
            )
            return 2
        if not isinstance(rt, dict) or "ID" not in rt:
            print(f"ERROR: invalid /RealTimeData payload: {rt!r}", file=sys.stderr)
            return 2
        device_id = str(rt["ID"])
        _LOGGER.info("Target device: %s @ %s", device_id, ip)

        snapshot = await _snapshot(session, ip, api_key, device_id)
        read_results = await _exercise_reads(session, ip, api_key, device_id)
        write_results = await _exercise_writes(session, ip, snapshot)
        restore_results, restore_ok = await _restore_and_verify(session, ip, snapshot)

    all_results = read_results + write_results + restore_results
    for res in all_results:
        line = repr(res)
        print(line, file=sys.stderr)
    fail = sum(1 for r in all_results if not r.ok)
    total = len(all_results)
    print(
        f"SUMMARY: {total - fail}/{total} ok, restore_ok={restore_ok}", file=sys.stderr
    )

    if not restore_ok:
        return 3
    return 0 if fail == 0 else 1


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-restore",
        action="store_true",
        required=False,
        help="Required flag — without it the script refuses to run.",
    )
    parser.add_argument(
        "--local-ip",
        default=None,
        help="Trydan local IP (default: V2C_LOCAL_IP env)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable DEBUG logging"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point used by ``python scripts/live_smoke_test.py``."""
    args = _parse_args(argv or sys.argv[1:])
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=logging.DEBUG if args.verbose else logging.INFO,
    )
    if not args.confirm_restore:
        print(
            "ABORT: --confirm-restore is required. This script mutates the device.\n"
            "Re-run with --confirm-restore once you've acknowledged the snapshot/restore behaviour.",
            file=sys.stderr,
        )
        return 2
    return asyncio.run(_main_async(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
