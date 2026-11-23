import json

from memory.similarity import cosine_similarity


class MemorySearch:
    def __init__(self, database):
        self.database = database

    def search(self, query: str, limit: int = 3):
        query_embedding = self.database.embedding_provider.embed(query)

        cursor = self.database.connection.cursor()

        cursor.execute("""
            SELECT id, content, embedding, created_at
            FROM memories
            WHERE embedding IS NOT NULL
        """)

        memories = cursor.fetchall()

        results = []

        for memory_id, content, embedding_json, created_at in memories:
            memory_embedding = json.loads(embedding_json)

            similarity = cosine_similarity(
                query_embedding,
                memory_embedding
            )

            results.append(
                (
                    memory_id,
                    content,
                    created_at,
                    similarity
                )
            )

        results.sort(
            key=lambda item: item[3],
            reverse=True
        )

        return results[:limit]