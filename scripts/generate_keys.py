"""
scripts/generate_keys.py

Run ONCE, offline, on a secure machine:
    python scripts/generate_keys.py

Produces:
    keys/private_key.pem   -> upload to the server's secrets manager /
                               environment ONLY. Never commit. Never put
                               in the desktop app.
    keys/public_key.pem    -> embed inside the desktop client (baked into
                               license/public_key.py at build time, see
                               scripts/embed_public_key.py).

If this private key ever leaks, ALL issued licenses must be considered
compromisable (an attacker could forge Professional licenses). Rotate by
generating a new keypair, shipping a client update with the new public
key, and having the server re-issue licenses signed with the new key on
next validation/renewal.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from license.crypto import LicenseSigner

if __name__ == "__main__":
    keys_dir = Path(__file__).parent.parent / "keys"
    keys_dir.mkdir(exist_ok=True)

    private_pem, public_pem = LicenseSigner.generate_new_keypair()

    (keys_dir / "private_key.pem").write_bytes(private_pem)
    (keys_dir / "public_key.pem").write_bytes(public_pem)

    print(f"Written:\n  {keys_dir / 'private_key.pem'}  (SECRET - server only)\n"
          f"  {keys_dir / 'public_key.pem'}   (embed in client)")
