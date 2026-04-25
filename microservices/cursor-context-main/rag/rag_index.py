#!/usr/bin/env python3
"""
RAG indexer for all workspace repos.
Uses nomic-embed-text via Ollama + ChromaDB for local vector storage.

Usage:
    python rag_index.py            # index everything (incremental)
    python rag_index.py --reset    # wipe DB and re-index from scratch
    python rag_index.py --stats    # show collection stats
"""

import argparse
import json
import pathlib
import sys
import time

REPOS = [
    "/Users/andrey/git/infra",
    "/Users/andrey/git/gitops",
    "/Users/andrey/git/frontend",
    "/Users/andrey/git/chessverse-monorepo",
    "/Users/andrey/git/monorepo",
    "/Users/andrey/git/RecoAlgo",
    "/Users/andrey/git/algo",
    "/Users/andrey/git/gitops-rg",
    "/Users/andrey/git/infra-rg",
    "/Users/andrey/git/cursor-context",
    "/Users/andrey/git/legacy-recognition",
]

EXTS = {".py", ".ts", ".tsx", ".yaml", ".yml", ".md", ".j2", ".sh"}
SKIP_DIRS = {
    "node_modules", ".venv", "venv", "__pycache__", ".git",
    "dist", "build", ".next", ".mypy_cache", ".pytest_cache",
    "coverage", ".tox", "eggs", ".eggs", "site-packages",
}

CHUNK_SIZE = 500      # tokens (approx chars / 4)
CHUNK_OVERLAP = 50
CHROMA_PATH = pathlib.Path(__file__).parent / ".chroma"
COLLECTION_NAME = "workspace"
EMBED_MODEL = "nomic-embed-text"
BATCH_SIZE = 32       # embed N chunks at once


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks by approximate token count (chars/4)."""
    char_size = chunk_size * 4
    char_overlap = overlap * 4
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + char_size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start += char_size - char_overlap
    return chunks


def collect_files() -> list[pathlib.Path]:
    files = []
    for repo in REPOS:
        path = pathlib.Path(repo)
        if not path.exists():
            print(f"  [skip] {repo} — not found")
            continue
        for f in path.rglob("*"):
            if f.is_dir():
                continue
            if any(part in SKIP_DIRS for part in f.parts):
                continue
            if f.suffix not in EXTS:
                continue
            # skip very large files (>500KB — generated/lock files)
            try:
                if f.stat().st_size > 500_000:
                    continue
            except OSError:
                continue
            files.append(f)
    return files


def file_mtime(f: pathlib.Path) -> str:
    return str(f.stat().st_mtime)


def embed_batch(ollama_client, texts: list[str]) -> list[list[float]]:
    result = ollama_client.embed(model=EMBED_MODEL, input=texts)
    return result.embeddings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Wipe DB and re-index")
    parser.add_argument("--stats", action="store_true", help="Show stats and exit")
    args = parser.parse_args()

    try:
        import chromadb
        import ollama as ollama_lib
    except ImportError:
        print("Missing deps. Run: pip install chromadb ollama")
        sys.exit(1)

    client = chromadb.PersistentClient(path=str(CHROMA_PATH))

    if args.reset:
        try:
            client.delete_collection(COLLECTION_NAME)
            print("Collection wiped.")
        except Exception:
            pass

    collection = client.get_or_create_collection(
        COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    if args.stats:
        print(f"Collection '{COLLECTION_NAME}': {collection.count()} chunks")
        print(f"Chroma path: {CHROMA_PATH}")
        return

    ollama_client = ollama_lib.Client()

    # Verify Ollama + model available
    try:
        ollama_client.embed(model=EMBED_MODEL, input=["test"])
    except Exception as e:
        print(f"Cannot reach Ollama / {EMBED_MODEL}: {e}")
        print("Make sure `ollama serve` is running and nomic-embed-text is pulled.")
        sys.exit(1)

    print("Collecting files...")
    files = collect_files()
    print(f"Found {len(files)} files across {len(REPOS)} repos\n")

    # Load existing mtimes from metadata to support incremental updates
    existing_ids: set[str] = set()
    try:
        existing = collection.get(include=["metadatas"])
        for meta in existing["metadatas"]:
            existing_ids.add(meta.get("file_mtime_key", ""))
    except Exception:
        pass

    ids_to_add: list[str] = []
    docs_to_add: list[str] = []
    metas_to_add: list[dict] = []

    skipped = 0
    processed = 0
    t0 = time.time()

    for i, fpath in enumerate(files):
        mtime = file_mtime(fpath)
        mtime_key = f"{fpath}:{mtime}"

        if mtime_key in existing_ids:
            skipped += 1
            continue

        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        text = text.strip()
        if not text:
            continue

        chunks = chunk_text(text)
        repo_name = next(
            (r.split("/")[-1] for r in REPOS if str(fpath).startswith(r)), "unknown"
        )
        rel_path = str(fpath).replace("/Users/andrey/git/", "")

        for j, chunk in enumerate(chunks):
            chunk_id = f"{fpath}::{j}::{mtime}"
            ids_to_add.append(chunk_id)
            docs_to_add.append(chunk)
            metas_to_add.append({
                "file": str(fpath),
                "rel_path": rel_path,
                "repo": repo_name,
                "chunk": j,
                "total_chunks": len(chunks),
                "file_mtime_key": mtime_key,
            })

        processed += 1

        # Flush batch
        if len(ids_to_add) >= BATCH_SIZE:
            _flush(collection, ollama_client, ids_to_add, docs_to_add, metas_to_add)
            ids_to_add, docs_to_add, metas_to_add = [], [], []

        # Progress every 50 files
        if (i + 1) % 50 == 0:
            elapsed = time.time() - t0
            rate = processed / elapsed if elapsed > 0 else 0
            remaining = (len(files) - i - 1) / rate / 60 if rate > 0 else 0
            print(f"  [{i+1}/{len(files)}] processed={processed} skipped={skipped} "
                  f"~{remaining:.1f}min remaining")

    # Flush remainder
    if ids_to_add:
        _flush(collection, ollama_client, ids_to_add, docs_to_add, metas_to_add)

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed/60:.1f} min.")
    print(f"  Files processed: {processed}")
    print(f"  Files skipped (unchanged): {skipped}")
    print(f"  Total chunks in DB: {collection.count()}")


def _flush(collection, ollama_client, ids, docs, metas):
    try:
        embeddings = embed_batch(ollama_client, docs)
        collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=docs,
            metadatas=metas,
        )
    except Exception as e:
        print(f"  [warn] batch upsert failed: {e}")


if __name__ == "__main__":
    main()
