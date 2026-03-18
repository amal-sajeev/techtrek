"""Generate a self-signed HTTPS cert valid for localhost and LAN IPs (for camera/HTTPS on same network)."""

import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

def get_lan_ips():
    """Return IPv4 addresses that are likely LAN (not loopback, not link-local)."""
    ips = []
    # Method 1: connect to a public IP to get the outbound interface IP (works on most OS)
    for dest in ("10.254.254.254", "8.8.8.8"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.5)
            s.connect((dest, 1))
            ip = s.getsockname()[0]
            s.close()
            if ip != "127.0.0.1" and not ip.startswith("169.254.") and ip not in ips:
                ips.append(ip)
            break
        except Exception:
            try:
                s.close()
            except Exception:
                pass
    # Method 2: enumerate addresses for hostname
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip != "127.0.0.1" and not ip.startswith("169.254.") and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    return ips


def main():
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        import ipaddress
    except ImportError:
        sys.exit("Install cryptography: pip install cryptography")

    root = Path(__file__).resolve().parent.parent
    cert_dir = root / "certs"
    cert_dir.mkdir(exist_ok=True)
    cert_file = cert_dir / "cert.pem"
    key_file = cert_dir / "key.pem"

    # SAN: localhost, 127.0.0.1, and all LAN IPs
    san_names = [
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
    ]
    lan_ips = get_lan_ips()
    for ip_str in lan_ips:
        try:
            san_names.append(x509.IPAddress(ipaddress.ip_address(ip_str)))
        except ValueError:
            pass

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "TechTrek Dev"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "TechTrek"),
    ])
    san = x509.SubjectAlternativeName(san_names)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=365))
        .add_extension(san, critical=False)
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )

    key_file.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    print(f"  Wrote {cert_file}")
    print(f"  Wrote {key_file}")
    print(f"  Valid for: localhost, 127.0.0.1" + (f", {', '.join(lan_ips)}" if lan_ips else ""))
    print("  Restart the server (python run.py) and use https://<your-IP>:8000 from other devices.")
    print("  On the other device, accept the browser warning once (Advanced -> Proceed); then camera will work.")


if __name__ == "__main__":
    main()
