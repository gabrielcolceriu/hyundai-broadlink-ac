"""Local BroadLink/DNA protocol used by Hyundai AC devices."""

from __future__ import annotations

import json
import math
import os
import socket
import struct
import time
from dataclasses import dataclass
from ipaddress import ip_address, ip_network
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

IV = bytes.fromhex("562e17996d093d28ddb3ba695a2e6f58")
MAGIC = bytes.fromhex("5aa5aa555aa5aa55")
INNER_MAGIC = bytes.fromhex("a5a55a5a")
DEFAULT_DEVICE_TYPE = 0x507C
SUPPORTED_DEVICE_TYPES = frozenset({0x507A, 0x507C})
COMMAND = 0x006A
BROADLINK_AUTH_COMMAND = 0x0065
BROADLINK_INIT_KEY = bytes.fromhex("097628343fe99e23765c1513accf8b02")
RESPONSE_COMMAND = 0x03EE
DEFAULT_PORT = 80
DEFAULT_TIMEOUT = 3.0
DISCOVERY_PAYLOAD = bytes.fromhex(
    "5aa5aa555aa5aa5502000000ea07041f0a001805000000001002000a688d0000ffc40000000006000000000000000000"
)
KNOWN_MAC_PREFIXES = ("24dfa7", "34ea34", "ec0bae", "b4430d", "a043b0")


class HyundaiAcError(Exception):
    """Raised when local AC communication fails."""


class HyundaiAcAuthError(HyundaiAcError):
    """Raised when BroadLink/DNA authentication fails."""

    def __init__(self, message: str, error_code: int | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code


class HyundaiAcLockedError(HyundaiAcAuthError):
    """Raised when a device reports the BroadLink/DNA locked flag."""


@dataclass(frozen=True)
class HyundaiAcDevice:
    """Connection details for one Hyundai AC."""

    host: str
    mac: str
    key: str
    devtype: int = DEFAULT_DEVICE_TYPE
    device_id: int = 1
    port: int = DEFAULT_PORT
    timeout: float = DEFAULT_TIMEOUT


@dataclass(frozen=True)
class HyundaiAcDiscovery:
    """Device details returned by BroadLink/DNA discovery."""

    host: str
    mac: str
    devtype: int
    name: str
    is_locked: bool


@dataclass(frozen=True)
class HyundaiAcAuth:
    """Local authentication details returned by a BroadLink/DNA device."""

    key: str
    device_id: int


class HyundaiAcClient:
    """Small synchronous local client for Hyundai AC devices."""

    def __init__(self, device: HyundaiAcDevice) -> None:
        self.device = device
        self._key = _parse_key(device.key)
        self._mac_reversed = _parse_mac(device.mac)[::-1]

    def get_state(self) -> dict[str, Any]:
        """Read the current raw state from the device."""

        return self._request("get", {})

    def set_param(self, param: str, value: Any) -> dict[str, Any]:
        """Set a single raw Hyundai parameter and return the resulting state."""

        return self._request("set", {param: value})

    def set_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Set multiple raw Hyundai parameters and return the resulting state."""

        return self._request("set", params)

    def _request(self, action: str, body: dict[str, Any]) -> dict[str, Any]:
        plain = self._encode_inner_payload(action, body)
        packet = self._build_packet(plain)

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(self.device.timeout)
            sock.sendto(packet, (self.device.host, self.device.port))
            try:
                response, _ = sock.recvfrom(2048)
            except TimeoutError as exc:
                raise HyundaiAcError(f"Timeout waiting for {self.device.host}:{self.device.port}") from exc

        return self._decode_response(response)

    def _encode_inner_payload(self, action: str, body: dict[str, Any]) -> bytes:
        body_bytes = json.dumps(body, separators=(",", ":")).encode()
        meaningful_length = 12 + len(body_bytes)
        plain_length = math.ceil((14 + len(body_bytes)) / 16) * 16
        plain = bytearray(plain_length)

        struct.pack_into("<H", plain, 0, meaningful_length)
        plain[2:6] = INNER_MAGIC
        plain[8] = 1 if action == "get" else 2
        plain[9] = 0x0B
        struct.pack_into("<I", plain, 10, len(body_bytes))
        plain[14 : 14 + len(body_bytes)] = body_bytes

        inner_checksum = _checksum(bytes(plain[2:6]) + bytes(plain[8:]))
        struct.pack_into("<H", plain, 6, inner_checksum)
        return bytes(plain)

    def _build_packet(self, plain_payload: bytes) -> bytes:
        encrypted = _aes_cbc_encrypt(plain_payload, self._key)
        packet = bytearray(56 + len(encrypted))

        packet[0:8] = MAGIC
        struct.pack_into("<H", packet, 0x24, self.device.devtype)
        struct.pack_into("<H", packet, 0x26, COMMAND)
        packet[0x28:0x2A] = os.urandom(2)
        packet[0x2A:0x30] = self._mac_reversed
        struct.pack_into("<I", packet, 0x30, self.device.device_id)
        struct.pack_into("<H", packet, 0x34, _checksum(plain_payload))
        packet[0x38:] = encrypted

        packet_for_checksum = bytearray(packet)
        packet_for_checksum[0x20:0x22] = b"\x00\x00"
        struct.pack_into("<H", packet, 0x20, _checksum(packet_for_checksum))
        return bytes(packet)

    def _decode_response(self, packet: bytes) -> dict[str, Any]:
        if len(packet) < 72:
            raise HyundaiAcError(f"Response too short: {len(packet)}")
        if struct.unpack_from("<H", packet, 0x26)[0] != RESPONSE_COMMAND:
            command = struct.unpack_from("<H", packet, 0x26)[0]
            raise HyundaiAcError(f"Unexpected response command: 0x{command:04x}")

        plain = _aes_cbc_decrypt(packet[0x38:], self._key)
        expected_checksum = struct.unpack_from("<H", packet, 0x34)[0]
        actual_checksum = _checksum(plain)
        if expected_checksum != actual_checksum:
            raise HyundaiAcError(
                f"Payload checksum mismatch: got 0x{actual_checksum:04x}, expected 0x{expected_checksum:04x}"
            )

        meaningful_length = struct.unpack_from("<H", plain, 0)[0]
        body_length = meaningful_length - 12
        if body_length < 0 or 14 + body_length > len(plain):
            raise HyundaiAcError(f"Invalid inner payload length: {meaningful_length}")

        return json.loads(plain[14 : 14 + body_length].decode())


def normalize_mac(mac: str) -> str:
    """Normalize a MAC address to lower-case colon notation."""

    compact = _compact_mac(mac)
    return ":".join(compact[index : index + 2] for index in range(0, 12, 2))


def discover_device_hosts(timeout: float = 2.0) -> dict[str, str]:
    """Discover BroadLink/DNA devices on the LAN and return MAC-to-host mapping."""

    devices: dict[str, str] = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.2)
        sock.bind(("0.0.0.0", 0))

        for host, port in (("255.255.255.255", 80), ("224.0.0.251", 80), ("224.0.0.251", 16680)):
            try:
                sock.sendto(DISCOVERY_PAYLOAD, (host, port))
            except OSError:
                continue

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                packet, remote = sock.recvfrom(2048)
            except TimeoutError:
                continue
            except OSError:
                break
            for mac in _extract_macs(packet):
                devices[mac] = remote[0]

    return devices


def discover_tcl_ac_devices(
    timeout: float = 2.0,
    seed_hosts: list[str] | None = None,
    scan_subnet: bool = False,
) -> list[HyundaiAcDiscovery]:
    """Discover Hyundai/BroadLink DNA AC devices on the LAN."""

    devices: dict[str, HyundaiAcDiscovery] = {}
    targets: list[tuple[str, int]] = [
        ("255.255.255.255", DEFAULT_PORT),
        ("224.0.0.251", DEFAULT_PORT),
        ("224.0.0.251", 16680),
    ]

    seen_targets = {target for target in targets}

    def add_target(host: str, port: int = DEFAULT_PORT) -> None:
        target = (host, port)
        if host and target not in seen_targets:
            seen_targets.add(target)
            targets.append(target)

    for host in seed_hosts or []:
        add_target(host)

    if scan_subnet:
        for host in _candidate_hosts(seed_hosts):
            add_target(host)

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.2)
        sock.bind(("0.0.0.0", 0))

        for host, port in targets:
            try:
                sock.sendto(DISCOVERY_PAYLOAD, (host, port))
            except OSError:
                continue

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                packet, remote = sock.recvfrom(2048)
            except TimeoutError:
                continue
            except OSError:
                break

            discovery = _parse_discovery_response(packet, remote[0])
            if discovery is not None:
                devices[discovery.mac] = discovery

    return sorted(devices.values(), key=lambda device: (device.host, device.mac))


def authenticate_tcl_ac_device(device: HyundaiAcDiscovery, timeout: float = 3.0) -> HyundaiAcAuth:
    """Authenticate to a discovered Hyundai/BroadLink DNA AC and return the local key."""

    if device.is_locked:
        raise HyundaiAcLockedError(
            f"{device.name} ({device.mac}) reports LOCKED=True and blocks local authentication",
            error_code=0xFFFF,
        )

    payload = bytearray(0x50)
    payload[0x04:0x14] = b"\x31" * 16
    payload[0x1E] = 0x01
    payload[0x2D] = 0x01
    payload[0x30:0x36] = b"Test 1"

    packet = _build_broadlink_packet(
        devtype=device.devtype,
        command=BROADLINK_AUTH_COMMAND,
        mac=device.mac,
        device_id=0,
        key=BROADLINK_INIT_KEY,
        plain_payload=bytes(payload),
    )

    response = _send_udp(device.host, DEFAULT_PORT, packet, timeout)
    if len(response) < 0x48:
        raise HyundaiAcError(f"Authentication response too short: {len(response)}")

    error_code = struct.unpack_from("<H", response, 0x22)[0]
    if error_code != 0:
        if error_code == 0xFFFF:
            raise HyundaiAcLockedError(
                f"Authentication failed with error 0x{error_code:04x}; the device may be locked",
                error_code=error_code,
            )
        raise HyundaiAcAuthError(f"Authentication failed with error 0x{error_code:04x}", error_code=error_code)

    plain = _aes_cbc_decrypt(response[0x38:], BROADLINK_INIT_KEY)
    return HyundaiAcAuth(
        key=plain[0x04:0x14].hex(),
        device_id=struct.unpack_from("<I", plain, 0)[0],
    )


def discover_authenticated_tcl_ac_devices(
    timeout: float = 3.0,
    seed_hosts: list[str] | None = None,
    scan_subnet: bool = True,
) -> list[tuple[HyundaiAcDiscovery, HyundaiAcAuth]]:
    """Discover and authenticate LAN devices that accept Hyundai local commands."""

    authenticated: list[tuple[HyundaiAcDiscovery, HyundaiAcAuth]] = []
    for discovery in discover_tcl_ac_devices(
        timeout=timeout,
        seed_hosts=seed_hosts,
        scan_subnet=scan_subnet,
    ):
        try:
            auth = authenticate_tcl_ac_device(discovery, timeout=timeout)
            client = HyundaiAcClient(
                HyundaiAcDevice(
                    host=discovery.host,
                    mac=discovery.mac,
                    key=auth.key,
                    device_id=auth.device_id,
                    timeout=timeout,
                )
            )
            client.get_state()
        except Exception:  # noqa: BLE001
            continue
        authenticated.append((discovery, auth))

    return authenticated


def find_device_host(
    mac: str,
    key: str,
    seed_hosts: list[str] | None = None,
    timeout: float = 3.0,
) -> str | None:
    """Find a device host by sending an authenticated local state request."""

    target_mac = normalize_mac(mac)
    discovered = discover_device_hosts(timeout=1.0)
    if discovered.get(target_mac):
        return discovered[target_mac]

    candidates = _candidate_hosts(seed_hosts)
    if not candidates:
        return None

    packets = []
    for devtype in SUPPORTED_DEVICE_TYPES:
        client = HyundaiAcClient(HyundaiAcDevice(host="0.0.0.0", mac=target_mac, key=key, devtype=devtype, timeout=timeout))
        packets.append((client, client._build_packet(client._encode_inner_payload("get", {}))))

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(0.2)
        for host in candidates:
            for _, packet in packets:
                try:
                    sock.sendto(packet, (host, DEFAULT_PORT))
                except OSError:
                    continue

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                response, remote = sock.recvfrom(2048)
            except TimeoutError:
                continue
            except OSError:
                break
            for client, _ in packets:
                try:
                    client._decode_response(response)
                except Exception:  # noqa: BLE001
                    continue
                return remote[0]

    return None


def _checksum(payload: bytes) -> int:
    value = 0xBEAF
    for byte in payload:
        value = (value + byte) & 0xFFFF
    return value


def _parse_mac(mac: str) -> bytes:
    return bytes.fromhex(_compact_mac(mac))


def _parse_key(key: str) -> bytes:
    compact = key.strip().lower()
    if len(compact) != 32:
        raise ValueError("Device key must be 16 bytes encoded as 32 hex characters")
    return bytes.fromhex(compact)


def _aes_cbc_encrypt(payload: bytes, key: bytes) -> bytes:
    encryptor = Cipher(algorithms.AES(key), modes.CBC(IV)).encryptor()
    return encryptor.update(payload) + encryptor.finalize()


def _aes_cbc_decrypt(payload: bytes, key: bytes) -> bytes:
    decryptor = Cipher(algorithms.AES(key), modes.CBC(IV)).decryptor()
    return decryptor.update(payload) + decryptor.finalize()


def _send_udp(host: str, port: int, packet: bytes, timeout: float) -> bytes:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(packet, (host, port))
        try:
            response, _ = sock.recvfrom(2048)
        except TimeoutError as exc:
            raise HyundaiAcError(f"Timeout waiting for {host}:{port}") from exc
    return response


def _build_broadlink_packet(
    devtype: int,
    command: int,
    mac: str,
    device_id: int,
    key: bytes,
    plain_payload: bytes,
) -> bytes:
    padded_payload = _pad16(plain_payload)
    encrypted = _aes_cbc_encrypt(padded_payload, key)
    packet = bytearray(56 + len(encrypted))

    packet[0:8] = MAGIC
    struct.pack_into("<H", packet, 0x24, devtype)
    struct.pack_into("<H", packet, 0x26, command)
    packet[0x28:0x2A] = os.urandom(2)
    packet[0x2A:0x30] = _parse_mac(mac)[::-1]
    struct.pack_into("<I", packet, 0x30, device_id)
    struct.pack_into("<H", packet, 0x34, _checksum(plain_payload))
    packet[0x38:] = encrypted
    struct.pack_into("<H", packet, 0x20, _checksum(bytes(packet)))
    return bytes(packet)


def _pad16(payload: bytes) -> bytes:
    padding = (16 - len(payload) % 16) % 16
    if padding == 0:
        return payload
    return payload + (b"\x00" * padding)


def _compact_mac(mac: str) -> str:
    compact = mac.replace(":", "").replace("-", "").lower()
    if len(compact) != 12:
        raise ValueError(f"Invalid MAC address: {mac}")
    return compact


def _extract_macs(packet: bytes) -> list[str]:
    macs = []
    for offset in range(0, max(0, len(packet) - 5)):
        compact = packet[offset : offset + 6][::-1].hex()
        if compact.startswith(KNOWN_MAC_PREFIXES):
            macs.append(normalize_mac(compact))
    return macs


def _parse_discovery_response(packet: bytes, host: str) -> HyundaiAcDiscovery | None:
    if len(packet) < 0x40:
        return None

    devtype = struct.unpack_from("<H", packet, 0x34)[0]
    if devtype not in SUPPORTED_DEVICE_TYPES:
        return None

    mac = normalize_mac(packet[0x3A:0x40][::-1].hex())
    name = packet[0x40:].split(b"\x00")[0].decode(errors="ignore").strip()
    return HyundaiAcDiscovery(
        host=host,
        mac=mac,
        devtype=devtype,
        name=name or f"Hyundai AC {mac[-8:]}",
        is_locked=bool(packet[0x7F]) if len(packet) > 0x7F else False,
    )


def _candidate_hosts(seed_hosts: list[str] | None = None) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    def add(host: str) -> None:
        if host and host not in seen:
            seen.add(host)
            candidates.append(host)

    for host in seed_hosts or []:
        add(host)

    for local_ip in _local_ipv4_addresses():
        try:
            network = ip_network(f"{local_ip}/24", strict=False)
        except ValueError:
            continue
        for host in network.hosts():
            add(str(host))

    return candidates


def _local_ipv4_addresses() -> set[str]:
    addresses: set[str] = set()

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            addresses.add(sock.getsockname()[0])
    except OSError:
        pass

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addresses.add(info[4][0])
    except OSError:
        pass

    return {
        address
        for address in addresses
        if not ip_address(address).is_loopback and not ip_address(address).is_link_local
    }
