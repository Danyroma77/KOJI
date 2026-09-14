# backend/scripts/benchmark/tokenizer_utils.py
from typing import List, Dict
import numpy as np
from sentence_transformers import SentenceTransformer

def chunk_text(text: str, tokenizer, chunk_size: int, overlap: int = 0) -> List[Dict]:
    tokens = tokenizer.encode(text, add_special_tokens=False)
    chunks = []
    for i in range(0, len(tokens), chunk_size - overlap):
        chunk_tokens = tokens[i:i + chunk_size]
        chunk_text = tokenizer.decode(chunk_tokens, skip_special_tokens=True)
        chunks.append({
            "text": chunk_text,
            "tokens": len(chunk_tokens),
            "start_token": i,
        })
    return chunks

def count_tokens(tokenizer, text: str) -> int:
    return len(tokenizer.encode(text, add_special_tokens=False))
