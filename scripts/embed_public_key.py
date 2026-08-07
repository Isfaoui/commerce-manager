"""
scripts/embed_public_key.py <path-to-public_key.pem>

Copies a generated public key into license/public_key.py so it gets
compiled into the client .exe by PyInstaller. Run this as part of your
release process, right after scripts/generate_keys.py (first time) or
after a key rotation.
"""
import sys
from pathlib import Path

TEMPLATE = '''"""
license/public_key.py

AUTO-GENERATED — do not edit by hand.
Regenerate with: python scripts/embed_public_key.py <public_key.pem>
"""

PUBLIC_KEY_PEM = b"""{pem}"""
'''

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/embed_public_key.py <path-to-public_key.pem>")
        sys.exit(1)

    pem_text = Path(sys.argv[1]).read_text()
    out_path = Path(__file__).parent.parent / "license" / "public_key.py"
    out_path.write_text(TEMPLATE.format(pem=pem_text))
    print(f"Embedded public key into {out_path}")
