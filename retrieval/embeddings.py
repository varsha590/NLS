"""Local embedding generation module for the Text-to-SQL RAG prototype."""

from typing import List
import numpy as np

from sentence_transformers import SentenceTransformer

EXPECTED_EMBEDDING_DIMENSION = 384


# ---------------------------------------------------------------------------
# Model metadata
# ---------------------------------------------------------------------------

class EmbeddingModel:
    """Wrapper for the local Sentence Transformers model.

    This model runs entirely locally on the machine. No API calls are required.
    """

    def __init__(self, model_name: str):
        self.model_name = model_name
        canonical_name = (
            f"sentence-transformers/{model_name}"
            if "/" not in model_name
            else model_name
        )
        self.model = SentenceTransformer(canonical_name)
        self.dim = self.model.get_sentence_embedding_dimension()
        if self.dim != EXPECTED_EMBEDDING_DIMENSION:
            raise ValueError(
                f"Embedding model {self.model_name!r} returns {self.dim} dimensions; "
                f"Qdrant requires {EXPECTED_EMBEDDING_DIMENSION}."
            )

    def embed(self, texts: List[str]) -> np.ndarray:
        """Generate embeddings for a list of text strings.

        Args:
            texts: List of input strings to embed.

        Returns:
            numpy array of shape (n_texts, dim) containing the embeddings.
        """
        return self.model.encode(texts, convert_to_numpy=True)

    def embed_single(self, text: str) -> np.ndarray:
        """Generate embedding for a single text string.

        Returns a numpy array of shape (dim,).
        """
        return self.model.encode(text, convert_to_numpy=True)


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def embed_texts(texts: List[str], model_name: str) -> np.ndarray:
    """Quick function to embed a list of texts.

    Args:
        texts: List of input strings.
        model_name: Sentence Transformers model name.

    Returns:
        numpy array of embeddings.
    """
    model = SentenceTransformer(model_name)
    return model.encode(texts, convert_to_numpy=True)