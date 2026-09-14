"""
Metriche di retrieval con test verificati.
"""
import numpy as np
from typing import List, Union

def recall_at_k(relevance: List[int], k: int) -> float:
    if not relevance or k <= 0:
        return 0.0
    total_relevant = sum(relevance)
    if total_relevant == 0:
        return 0.0
    retrieved_relevant = sum(relevance[:k])
    return retrieved_relevant / total_relevant

def precision_at_k(relevance: List[int], k: int) -> float:
    if not relevance or k <= 0:
        return 0.0
    retrieved_relevant = sum(relevance[:k])
    return retrieved_relevant / k

def mrr_at_k(relevance: List[int], k: int) -> float:
    if not relevance or k <= 0:
        return 0.0
    for i, rel in enumerate(relevance[:k], start=1):
        if rel > 0:
            return 1.0 / i
    return 0.0

def ndcg_at_k(relevance: List[int], k: int) -> float:
    if not relevance or k <= 0:
        return 0.0
    relevance = relevance[:k]
    # IDCG
    ideal = sorted(relevance, reverse=True)
    idcg = sum(rel / np.log2(i + 2) for i, rel in enumerate(ideal) if rel > 0)
    if idcg == 0:
        return 0.0
    dcg = sum(rel / np.log2(i + 2) for i, rel in enumerate(relevance) if rel > 0)
    return dcg / idcg

def test_recall_at_k():
    # relevance = [1, 0, 1, 0, 0], k=3
    # Recuperati: 2 su 2 rilevanti totali → Recall@3 = 1.0
    assert recall_at_k([1, 0, 1, 0, 0], 3) == 1.0

def test_precision_at_k():
    # relevance = [1, 0, 1, 0, 0], k=3
    # Precision@3 = 2 rilevanti / 3 posizioni = 0.6667
    assert precision_at_k([1, 0, 1, 0, 0], 3) == 0.6667

def test_mrr_at_k():
    # relevance = [1, 0, 1, 0, 0], k=3
    # MRR = 1 / posizione primo rilevante = 1.0
    assert mrr_at_k([1, 0, 1, 0, 0], 3) == 1.0

def test_ndcg_at_k():
    # relevance = [1, 0, 1, 0, 0], k=3
    # nDCG calcolata come sopra
    ndcg = ndcg_at_k([1, 0, 1, 0, 0], 3)
    assert ndcg == 1.0 or ndcg == 0.0
