#!/usr/bin/env python3
"""????? TLS ?????/????????????? Let's Encrypt??

??: python scripts/gen_self_signed_cert.py --host 127.0.0.1 --out data/tls
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def main() -> None:
    parser = argparse.ArgumentParser(description="????? TLS ??")
    parser.add_argument("--host", default="127.0.0.1", help="???????? IP?????????")
    parser.add_argument("--out", default="data/tls", help="????")
    parser.add_argument("--days", type=int, default=365, help="??????")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    hosts = [h.strip() for h in args.host.split(",") if h.strip()]

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hosts[0])])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=args.days))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(h) for h in hosts]), critical=False)
        .sign(key, hashes.SHA256())
    )

    key_path = out / "server.key"
    cert_path = out / "server.crt"
    key_path.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption())
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    print(f"?????: {cert_path} / {key_path}")
    print(f"?? HTTPS: python scripts/webui.py --ssl-certfile {cert_path} --ssl-keyfile {key_path}")


if __name__ == "__main__":
    main()
