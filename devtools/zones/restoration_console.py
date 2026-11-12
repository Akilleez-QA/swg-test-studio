"""Typed CentralServer console request for profiles without the fixture console binary.

Sends exactly one `game <id> runScript fixture.protocol_bot inspect <identity>`
ConGenericMessage to the fixture's private CentralServer console port. No other
command, script or argument can be expressed. Framing follows TcpClient
(int32 length) and GameNetworkMessage (uint16 count, uint32 type CRC, fields).
"""
import ipaddress
import re
import socket
import struct

PORT = 61000
METHODS = {'botInspect': 'inspect'}
IDENTITY = re.compile(r'[1-9][0-9]{0,18}:[1-9][0-9]{0,9}:Cap[a-z]{12}')


def crc(text):
    """sharedFoundation Crc::calculate: MSB-first CRC-32, initial and final xor 0xFFFFFFFF."""
    value = 0xFFFFFFFF
    for byte in text.encode('latin-1'):
        value ^= byte << 24
        for _ in range(8):
            value = ((value << 1) ^ 0x04C11DB7) if value & 0x80000000 else value << 1
        value &= 0xFFFFFFFF
    return value ^ 0xFFFFFFFF


TYPE = crc('ConGenericMessage')


def line(command, worker, bot):
    if command not in METHODS:
        raise ValueError('This server profile supports read-only bot inspection only')
    if type(worker) is not int or not 0 < worker <= 2147483647:
        raise ValueError('Invalid game server id')
    ident = f"{bot['player']}:{bot['station']}:{bot['character']}"
    if not IDENTITY.fullmatch(ident):
        raise ValueError('Bot identity does not match the fixture contract')
    return f'game {worker} runScript fixture.protocol_bot {METHODS[command]} {ident}'


def frame(text, serial=1):
    body = text.encode('latin-1')
    payload = struct.pack('<HIH', 3, TYPE, len(body)) + body + struct.pack('<I', serial)
    return struct.pack('<i', len(payload)) + payload


def private_address(host):
    address = ipaddress.ip_address(host)
    if address.version != 4 or not (address.is_loopback or address.is_private):
        raise ValueError("Use the fixture's private CentralServer IPv4; never a public console")
    return str(address)


def network_owner(row, inspect):
    """The container whose network namespace `row` joins (Compose network_mode service:X), or `row` itself.

    CentralServer reaches its TaskManager only at 127.0.0.1, so a fixture may run Central in the
    TaskManager container's namespace; its console then listens on that container's address. The
    owner must belong to the same Compose project.
    """
    mode = row.get('HostConfig', {}).get('NetworkMode', '')
    if not mode.startswith('container:'):
        return row
    owner = inspect(mode[len('container:'):])[0]
    project = row['Config']['Labels'].get('com.docker.compose.project')
    if not project or owner['Config']['Labels'].get('com.docker.compose.project') != project:
        raise RuntimeError('Central shares the network of a container outside its fixture project')
    return owner


def central_address(rows, inspect=None):
    """The one private address of an inspected central container (or of the container whose network it joins)."""
    row = network_owner(rows[0], inspect) if inspect else rows[0]
    addresses = [n['IPAddress'] for n in row['NetworkSettings']['Networks'].values() if n.get('IPAddress')]
    if len(addresses) != 1:
        raise RuntimeError('Cannot select one central fixture address')
    return private_address(addresses[0])


def _read(conn, size):
    data = b''
    while len(data) < size:
        chunk = conn.recv(size - len(data))
        if not chunk:
            raise RuntimeError('Console connection closed')
        data += chunk
    return data


def request(host, text, *, timeout=12.0, connect=socket.create_connection):
    """One request and its reply; zero-length keepalive frames are skipped."""
    with connect((private_address(host), PORT), timeout=timeout) as conn:
        conn.sendall(frame(text))
        for _ in range(16):
            (size,) = struct.unpack('<i', _read(conn, 4))
            if size == 0:
                continue
            if not 6 <= size <= 2 * 1024 * 1024:
                break
            payload = _read(conn, size)
            count, kind = struct.unpack_from('<HI', payload)
            if kind == TYPE and count == 3 and size >= 8:
                (length,) = struct.unpack_from('<H', payload, 6)
                if size >= 8 + length:
                    return payload[8:8 + length].decode('latin-1').strip()
    raise RuntimeError('No complete console response within bounds')
