"""www.eizoglobal.com's server doesn't send its intermediate CA certificate
("Cybertrust Japan SureServer CA G4") during the TLS handshake -- verified
2026-09-23 with `openssl s_client -showcerts` (only the leaf cert comes
back; `-CAfile <certifi bundle>` then fails with "unable to get local
issuer certificate" / "unable to verify the first certificate"). Browsers
and curl tolerate this (they either fetch the missing intermediate via the
cert's own AIA "CA Issuers" URL, or already have it cached from an OS trust
store); Python's `requests` (via `certifi`) does neither, and just fails.

The fix is the standard one for a server with an incomplete chain: supply
the missing intermediate ourselves. `cybertrust_japan_sureserver_ca_g4.pem`
in this directory was fetched straight from the leaf cert's own "CA
Issuers" AIA URL (http://crl.cybertrust.ne.jp/SureServer/ovcag4/ovcag4.crt)
and converted from DER to PEM. It chains up to "Security Communication
RootCA2", which *is* already in certifi's bundle, so appending just this
one intermediate is enough -- confirmed with
`openssl s_client -CAfile <certifi+this> -connect www.eizoglobal.com:443`
returning "Verify return code: 0 (ok)".
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import certifi

_INTERMEDIATE_PATH = Path(__file__).parent / "cybertrust_japan_sureserver_ca_g4.pem"

_combined_bundle_path: str | None = None


def combined_ca_bundle_path() -> str:
    """Certifi's default trust store plus the intermediate above, written
    once per process to a temp file (never committed to the repo --
    certifi's own bundle is regenerated on every install/upgrade, so a
    checked-in combined copy would silently go stale).
    """
    global _combined_bundle_path
    if _combined_bundle_path is None:
        certifi_bundle = Path(certifi.where()).read_text(encoding="utf-8")
        intermediate = _INTERMEDIATE_PATH.read_text(encoding="utf-8")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".pem", prefix="eizo_ca_bundle_", delete=False, encoding="utf-8"
        ) as f:
            f.write(certifi_bundle)
            f.write("\n")
            f.write(intermediate)
            _combined_bundle_path = f.name
    return _combined_bundle_path
