from __future__ import annotations

import os
import platform
import re
from typing import Any, Tuple

import chromadb
import numpy as np
from sentence_transformers import SentenceTransformer

from chunker import PythonChunker


def resolve_embedder_device() -> Tuple[Any, str]:
    """Pick the best runtime: CUDA/ROCm -> DirectML -> CPU."""
    forced = os.getenv("RAG_EMBED_DEVICE", "").strip().lower()
    if forced == "cpu":
        return "cpu", "cpu (forced)"
    if forced == "cuda":
        return "cuda", "cuda/rocm (forced)"
    if forced == "directml":
        try:
            import torch_directml

            return torch_directml.device(), "directml (forced)"
        except Exception:
            return "cpu", "cpu (directml unavailable)"

    try:
        import torch

        if torch.cuda.is_available():
            if getattr(torch.version, "hip", None):
                return "cuda", "rocm"
            return "cuda", "cuda"
    except Exception:
        pass

    if platform.system().lower() == "windows":
        try:
            import torch_directml

            return torch_directml.device(), "directml"
        except Exception:
            pass

    return "cpu", "cpu"


class CodeRAG:
    def __init__(self, persist_dir: str = "./chroma_db"):
        if platform.system().lower() == "windows":
            # Avoid Windows symlink privilege issues in HuggingFace cache.
            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")

        self.client = chromadb.PersistentClient(path=persist_dir)
        self.collection = self.client.get_or_create_collection(
            name="code_chunks",
            metadata={"hnsw:space": "cosine"},
        )

        self.embed_device, self.embed_backend = resolve_embedder_device()
        self.embed_batch_size = int(os.getenv("RAG_EMBED_BATCH_SIZE", "32"))
        self.embed_model = os.getenv("RAG_EMBED_MODEL", "microsoft/codebert-base")
        self.hf_cache = os.getenv("RAG_HF_HOME", "").strip()
        embedder_kwargs = {}
        if self.hf_cache:
            os.makedirs(self.hf_cache, exist_ok=True)
            os.environ.setdefault("HF_HOME", self.hf_cache)
            os.environ.setdefault("TRANSFORMERS_CACHE", self.hf_cache)
            embedder_kwargs["cache_folder"] = self.hf_cache

        try:
            self.embedder = SentenceTransformer(
                self.embed_model,
                device=self.embed_device,
                **embedder_kwargs,
            )
        except Exception as exc:
            print(f"[CodeRAG] SentenceTransformer init failed: {exc}")
            self.embedder = _HashingEmbedder(dim=768)
            self.embed_backend = f"{self.embed_backend}+hashing-fallback"
        self.chunker = PythonChunker()
        print(
            f"[CodeRAG] backend={self.embed_backend}, "
            f"model={self.embed_model}, cache={self.hf_cache or 'default'}"
        )

    def _encode_texts(self, texts):
        try:
            return self.embedder.encode(
                texts,
                batch_size=self.embed_batch_size,
                show_progress_bar=False,
                normalize_embeddings=True,
            )
        except Exception as exc:
            print(f"[CodeRAG] embedding encode failed: {exc}")
            if not isinstance(self.embedder, _HashingEmbedder):
                self.embedder = _HashingEmbedder(dim=768)
                if "hashing-fallback" not in self.embed_backend:
                    self.embed_backend = f"{self.embed_backend}+hashing-fallback"
                    print(f"[CodeRAG] switched to {self.embed_backend}")
            return self.embedder.encode(
                texts,
                batch_size=self.embed_batch_size,
                show_progress_bar=False,
                normalize_embeddings=True,
            )

    def add_code(self, code: str, filepath: str):
        chunks = self.chunker.chunk(code, filepath)
        if not chunks:
            chunks = [
                {
                    "file": filepath,
                    "name": "whole_file",
                    "type": "file",
                    "start_line": 1,
                    "end_line": len(code.splitlines()),
                    "code": code,
                }
            ]

        ids = []
        documents = []
        metadatas = []

        for idx, chunk in enumerate(chunks):
            chunk_id = f"{filepath}_{chunk['start_line']}_{idx}"
            ids.append(chunk_id)
            documents.append(chunk["code"])
            metadatas.append(
                {
                    "file": chunk["file"],
                    "name": chunk["name"],
                    "type": chunk["type"],
                    "start_line": chunk["start_line"],
                    "end_line": chunk["end_line"],
                }
            )

        embeddings = self._encode_texts(documents).tolist()
        try:
            self.collection.add(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
                embeddings=embeddings,
            )
        except Exception as exc:
            print(f"[CodeRAG] collection.add failed: {exc}")

    def search(self, query: str, top_k: int = 5):
        query_embedding = self._encode_texts([query]).tolist()
        try:
            results = self.collection.query(
                query_embeddings=query_embedding,
                n_results=top_k,
                include=["documents", "metadatas"],
            )
        except Exception as exc:
            print(f"[CodeRAG] collection.query failed: {exc}")
            return []
        return results["documents"][0] if results["documents"] else []

    def search_by_code(self, code_snippet: str, top_k: int = 5):
        return self.search(code_snippet, top_k)

    def get_all_chunks(self, limit: int = 1000):
        return self.collection.get(limit=limit, include=["documents", "metadatas"])


class _HashingEmbedder:
    """Offline-safe fallback embedder to keep the service runnable."""

    def __init__(self, dim: int = 768):
        self.dim = dim

    def encode(
        self,
        texts,
        batch_size: int = 32,
        show_progress_bar: bool = False,
        normalize_embeddings: bool = True,
    ):
        del batch_size, show_progress_bar  # Keep same signature as SentenceTransformer.
        vectors = []
        for text in texts:
            vec = np.zeros(self.dim, dtype=np.float32)
            for token in re.findall(r"\w+", text.lower()):
                vec[hash(token) % self.dim] += 1.0
            if normalize_embeddings:
                norm = np.linalg.norm(vec)
                if norm > 0:
                    vec /= norm
            vectors.append(vec)
        return np.vstack(vectors)
