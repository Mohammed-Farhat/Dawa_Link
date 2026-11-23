"""A small SMTP server on 127.0.0.1, for the sender's tests (docs/09 FX-7 to FX-9).

The standard library no longer ships one (`smtpd` left in Python 3.12), so this speaks
just enough of the protocol: EHLO, STARTTLS, AUTH PLAIN, MAIL, RCPT, DATA and QUIT. It
can refuse a login or an address, or hang up at a chosen command, like a server that
goes away. A certificate for it is made with `cryptography`, already a dependency.
"""

import base64
import contextlib
import datetime as dt
import ipaddress
import socket
import socketserver
import ssl
import threading
from dataclasses import dataclass, field
from email import message_from_bytes
from email.message import Message
from pathlib import Path
from types import TracebackType
from typing import Self

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


@dataclass
class Login:
    user: str
    password: str
    over_tls: bool


@dataclass
class Seen:
    """What the server was told, in order."""

    commands: list[str] = field(default_factory=list)
    logins: list[Login] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)


def make_certificate(folder: Path) -> tuple[Path, Path]:
    """A self-signed certificate for 127.0.0.1 and localhost: (certificate, key)."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = dt.datetime.now(dt.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = folder / "smtp-cert.pem", folder / "smtp-key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


class FakeSmtpServer:
    """Runs on its own thread while the `with` block lasts. `port` is where it listens.

    `tls`: offers STARTTLS with this context. `password`: offers AUTH, and accepts only
    this password. `refuses`: addresses turned away at RCPT. `hang_up_at`: the command
    (EHLO, AUTH, MAIL, DATA…) at which it closes the connection without a word.
    """

    def __init__(
        self,
        *,
        tls: ssl.SSLContext | None = None,
        password: str | None = None,
        refuses: frozenset[str] = frozenset(),
        hang_up_at: str | None = None,
    ) -> None:
        self.tls, self.password, self.refuses, self.hang_up_at = tls, password, refuses, hang_up_at
        self.seen = Seen()
        fake = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                fake._converse(self.request)

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = True

            def handle_error(self, request: object, client_address: object) -> None:
                pass  # a client that gave up mid-way (a failed TLS handshake) is expected

        self._server = Server(("127.0.0.1", 0), Handler)
        self.port: int = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self._server.shutdown()
        self._server.server_close()

    def _converse(self, connection: socket.socket) -> None:
        # The client may hang up, or fail its TLS handshake: both are expected here.
        with contextlib.suppress(OSError):
            self._speak(connection)

    def _speak(self, connection: socket.socket) -> None:
        reader = connection.makefile("rb")
        over_tls = False

        def reply(*lines: str) -> None:
            for index, text in enumerate(lines):
                separator = " " if index == len(lines) - 1 else "-"
                connection.sendall(f"{text[:3]}{separator}{text[4:]}\r\n".encode())

        reply("220 fake.test ready")
        while raw := reader.readline():
            line = raw.decode().rstrip("\r\n")
            verb = line.split(" ", 1)[0].upper()
            self.seen.commands.append(verb)
            if verb == self.hang_up_at:
                # Shut down, not just close: the request handler still holds the socket.
                connection.shutdown(socket.SHUT_RDWR)
                return
            if verb in ("EHLO", "HELO"):
                offers = ["250 fake.test"]
                if self.tls is not None and not over_tls:
                    offers.append("250 STARTTLS")
                if self.password is not None:
                    offers.append("250 AUTH PLAIN")
                reply(*offers)
            elif verb == "STARTTLS" and self.tls is not None:
                reply("220 go ahead")
                connection = self.tls.wrap_socket(connection, server_side=True)
                reader, over_tls = connection.makefile("rb"), True
            elif verb == "AUTH":
                _, user, password = base64.b64decode(line.split()[2]).decode().split("\0")
                self.seen.logins.append(Login(user, password, over_tls))
                ok = password == self.password
                reply("235 accepted" if ok else "535 Authentication credentials invalid")
            elif verb == "RCPT":
                address = line.partition(":")[2].strip().strip("<>")
                reply("550 Address not verified" if address in self.refuses else "250 ok")
            elif verb == "DATA":
                reply("354 go on")
                body = b""
                while (part := reader.readline()) not in (b".\r\n", b""):
                    body += part[1:] if part.startswith(b"..") else part
                self.seen.messages.append(message_from_bytes(body))
                reply("250 queued")
            elif verb == "QUIT":
                reply("221 bye")
                connection.close()
                return
            elif verb in ("MAIL", "RSET", "NOOP"):
                reply("250 ok")
            else:
                reply("502 not here")


def client_context(certificate: Path) -> ssl.SSLContext:
    """What the sender uses in a test: checks the certificate like the real one, against
    the test's own certificate instead of the system's."""
    return ssl.create_default_context(cafile=str(certificate))


def server_context(certificate: Path, key: Path) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(certificate), str(key))
    return context
