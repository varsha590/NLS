#!/usr/bin/env python3
"""Measure cosine similarity for sibling value pairs and typos using all-MiniLM-L6-v2."""

from sentence_transformers import SentenceTransformer
import numpy as np

model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

pairs = [
    ("Electronics", "Electrical"),
    ("North", "South"),
    ("Active", "Inactive"),
    ("Electroncis", "Electronics"),  # typo
    ("Electonics", "Electronics"),   # typo
    ("Electrical", "Electronics"),   # reverse
    ("South", "North"),              # reverse
    ("Inactive", "Active"),          # reverse
]

print("Cosine similarities (all-MiniLM-L6-v2):")
print("=" * 60)
for a, b in pairs:
    emb = model.encode([a, b], convert_to_numpy=True)
    sim = np.dot(emb[0], emb[1]) / (np.linalg.norm(emb[0]) * np.linalg.norm(emb[1]))
    print(f"  {a:15s} <-> {b:15s}  =  {sim:.4f}")

# Also test random word pairs for noise floor
print("\nRandom word pairs (noise floor, 1000 samples):")
import random
words = open("/usr/share/dict/words").read().splitlines()
words = [w for w in words if w.isalpha() and 3 <= len(w) <= 12]
sims = []
for _ in range(1000):
    a, b = random.sample(words, 2)
    emb = model.encode([a, b], convert_to_numpy=True)
    sim = np.dot(emb[0], emb[1]) / (np.linalg.norm(emb[0]) * np.linalg.norm(emb[1]))
    sims.append(sim)
sims = np.array(sims)
print(f"  mean:   {sims.mean():.4f}")
print(f"  std:    {sims.std():.4f}")
print(f"  95th:   {np.percentile(sims, 95):.4f}")
print(f"  99th:   {np.percentile(sims, 99):.4f}")
print(f"  99.9th: {np.percentile(sims, 99.9):.4f}")
print(f"  max:    {sims.max():.4f}")

# Test difflib for typos
print("\nDifflib SequenceMatcher ratios for typos:")
import difflib
typos = [
    ("Electroncis", "Electronics"),
    ("Electonics", "Electronics"),
    ("Electrikal", "Electrical"),
    ("Nort", "North"),
    ("Actve", "Active"),
]
for a, b in typos:
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    print(f"  {a:15s} vs {b:15s}  =  {ratio:.4f}")