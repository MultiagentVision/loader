# Workspace RAG

Local vector search over all 11 workspace repos using `nomic-embed-text` + ChromaDB.

## Setup

```bash
cd /Users/andrey/git/cursor-context/rag
pip install -r requirements.txt
```

Requires Ollama running with `nomic-embed-text`:
```bash
brew services start ollama
ollama pull nomic-embed-text
```

## Index (first run ~30-45 min, then incremental)

```bash
python rag_index.py            # incremental update
python rag_index.py --reset    # wipe and re-index everything
python rag_index.py --stats    # show DB stats
```

## Query

```bash
python rag_query.py "how does the minio LVM fix work"
python rag_query.py "ClearML agent getaddrinfo fix"
python rag_query.py "warp size 480 constraint" --repo algo
python rag_query.py "kubectl minio pod" --ext yaml
python rag_query.py "clearml dns" --top 10
```

## Repos indexed

| Repo | ~Files |
|------|--------|
| infra | 1,526 |
| monorepo | 414 |
| chessverse-monorepo | 395 |
| algo | 298 |
| frontend | 199 |
| gitops | 137 |
| legacy-recognition | 66 |
| RecoAlgo | 33 |
| infra-rg | 25 |
| gitops-rg | 19 |
| cursor-context | 17 |

## Integration with Continue (@codebase in Cursor)

Continue's built-in `@codebase` uses the same `nomic-embed-text` model
via Ollama for its own index. Configure in `~/.continue/config.json`.
