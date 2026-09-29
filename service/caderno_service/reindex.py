"""Index the notebook by hand: `python -m caderno_service.reindex [--rebuild]`.

--rebuild empties the index and rebuilds it from the files, which is always
safe because the files are the source of truth (revision history is lost).
"""

import argparse

from .config import Settings
from .embed import Embedder
from .store import Store


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args()
    s = Settings.from_env()
    store = Store(s.database_url, s.notebook, Embedder(s))
    store.migrate()
    r = store.rebuild() if a.rebuild else store.reconcile()
    print(r.summary())
    print(store.counts())


if __name__ == "__main__":
    main()
