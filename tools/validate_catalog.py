"""Validate the canonical V2 catalog offline, without database access."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.catalog import Catalog, CatalogError


def main(argv=None):
    parser = argparse.ArgumentParser(description='Validate LunexEconom game catalog')
    parser.add_argument('--data-dir', type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        catalog = Catalog(args.data_dir)
    except CatalogError as exc:
        parser.exit(1, f'ERROR: {exc}\n')
    for kind in ('products', 'buildings', 'recipes'):
        print(f'{kind}: {len(catalog.data[kind])}')
    print(f'OK catalog SHA-256: {catalog.version} (balance: draft)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
