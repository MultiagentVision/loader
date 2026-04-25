#!/usr/bin/env python3
"""
RAG query CLI — search indexed workspace repos.

Usage:
    python rag_query.py "how does the minio LVM fix work"
    python rag_query.py "ClearML agent getaddrinfo fix" --top 5
    python rag_query.py "warp size 480" --repo algo
    python rag_query.py "kubectl get pods" --ext yaml
"""

import argparse
import pathlib
import sys

CHROMA_PATH = pathlib.Path(__file__).parent / ".chroma"
COLLECTION_NAME = "workspace"
EMBED_MODEL = "nomic-embed-text"


def main():
    parser = argparse.ArgumentParser(description="Search indexed workspace repos")
    parser.add_argument("query", help="Natural language query")
    parser.add_argument("--top", type=int, default=5, help="Number of results (default: 5)")
    parser.add_argument("--repo", help="Filter by repo name (e.g. algo, infra)")
    parser.add_argument("--ext", help="Filter by file extension (e.g. py, yaml, md)")
    args = parser.parse_args()

    try:
        import chromadb
        import ollama as ollama_lib
    except ImportError:
        print("Missing deps. Run: pip install chromadb ollama")
        sys.exit(1)

    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    try:
        collection = client.get_collection(COLLECTION_NAME)
    except Exception:
        print(f"Collection '{COLLECTION_NAME}' not found.")
        print("Run: python rag_index.py")
        sys.exit(1)

    ollama_client = ollama_lib.Client()
    try:
        result = ollama_client.embed(model=EMBED_MODEL, input=[args.query])
        query_embedding = result.embeddings[0]
    except Exception as e:
        print(f"Cannot embed query: {e}")
        print("Make sure Ollama is running: brew services start ollama")
        sys.exit(1)

    where = {}
    if args.repo:
        where["repo"] = {"$eq": args.repo}
    if args.ext:
        # filter by file extension in rel_path
        # chromadb doesn't support suffix filter directly, so we post-filter
        pass

    query_kwargs = dict(
        query_embeddings=[query_embedding],
        n_results=args.top * 3 if args.ext else args.top,  # over-fetch for post-filter
        include=["documents", "metadatas", "distances"],
    )
    if where:
        query_kwargs["where"] = where

    results = collection.query(**query_kwargs)

    docs = results["documents"][0]
    metas = results["metadatas"][0]
    distances = results["distances"][0]

    # Post-filter by extension if requested
    if args.ext:
        filtered = [
            (d, m, dist)
            for d, m, dist in zip(docs, metas, distances)
            if m["rel_path"].endswith(f".{args.ext}")
        ]
        docs, metas, distances = zip(*filtered[:args.top]) if filtered else ([], [], [])

    print(f'\nQuery: "{args.query}"')
    print(f"Top {min(args.top, len(docs))} results:\n")
    print("─" * 80)

    for i, (doc, meta, dist) in enumerate(zip(docs, metas, distances), 1):
        score = 1 - dist  # cosine similarity
        rel = meta.get("rel_path", meta.get("file", "?"))
        chunk_n = meta.get("chunk", 0)
        total = meta.get("total_chunks", 1)

        print(f"[{i}] {rel}  (chunk {chunk_n+1}/{total})  score={score:.3f}")
        print()
        # Show first 400 chars of chunk
        snippet = doc[:400].replace("\n", "\n    ")
        print(f"    {snippet}")
        if len(doc) > 400:
            print(f"    ... ({len(doc)} chars total)")
        print()
        print("─" * 80)


if __name__ == "__main__":
    main()
