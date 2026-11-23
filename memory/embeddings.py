import requests


class EmbeddingProvider:
    def __init__(self, model: str = "nomic-embed-text"):
        self.model = model
        self.url = "http://localhost:11434/api/embed"

    def embed(self, text: str):
        response = requests.post(
            self.url,
            json={
                "model": self.model,
                "input": text
            },
            timeout=120
        )

        response.raise_for_status()

        data = response.json()

        return data["embeddings"][0]