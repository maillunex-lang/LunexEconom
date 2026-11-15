#!/usr/bin/env python3
"""Sign update.json or content.json with a SEPARATE offline manifest key."""
import argparse
from manifest_security import sign_file, verify_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    parser.add_argument("--private-key", required=True)
    parser.add_argument("--public-key", help="Verify output with matching public key")
    args = parser.parse_args()
    target = sign_file(args.manifest, args.private_key)
    if args.public_key and not verify_file(args.manifest, target, args.public_key):
        parser.error("Signature verification failed")
    print("Signed manifest:", args.manifest, "signature:", target)


if __name__ == "__main__":
    main()
