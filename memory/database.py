import sqlite3
from pathlib import Path
import json
from memory.embeddings import EmbeddingProvider
from memory.similarity import cosine_similarity


from config import BASE_DIR

# Путь считается от папки проекта, а не от папки, из которой запустили
# программу: иначе окно, запущенное ярлыком или из IDE, создало бы
# новую пустую базу в другом месте.
DATABASE_DIR = Path(BASE_DIR) / "data" / "database"
DATABASE_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_PATH = DATABASE_DIR / "jarvis.db"


class Database:
    def __init__(self):
        # check_same_thread=False: в окне память используется из рабочего
        # потока, а не из того, где создана база. Одновременных обращений
        # нет — ядро (core/jarvis.py) обрабатывает один запрос за раз.
        self.connection = sqlite3.connect(
            DATABASE_PATH,
            check_same_thread=False
        )
        self.embedding_provider = EmbeddingProvider()
        self._create_tables()

    def _create_tables(self):
        cursor = self.connection.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                embedding TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("PRAGMA table_info(memories)")
        columns = [column[1] for column in cursor.fetchall()]

        if "embedding" not in columns:
            cursor.execute(
                "ALTER TABLE memories ADD COLUMN embedding TEXT"
            )

        self.connection.commit()

    def add_memory(self, content: str):
        embedding = self.embedding_provider.embed(content)

        embedding_json = json.dumps(embedding)

        cursor = self.connection.cursor()

        cursor.execute(
            """
            INSERT INTO memories (content, embedding)
            VALUES (?, ?)
            """,
            (content, embedding_json)
        )

        self.connection.commit()

    def get_memories(self):
        cursor = self.connection.cursor()

        cursor.execute("""
            SELECT id, content, created_at
            FROM memories
            ORDER BY id ASC
        """)

        return cursor.fetchall()

    def search_memories(self, query: str):
        cursor = self.connection.cursor()

        words = query.lower().split()

        stop_words = {
            "я", "ты", "он", "она", "мы", "вы",
            "а", "и", "или", "но",
            "в", "на", "из", "к", "у", "с",
            "какой", "какая", "какое", "какие",
            "что", "где", "когда", "как",
            "мой", "моя", "моё", "мои"
        }

        important_words = [
            word.strip(".,!?;:\"()")
            for word in words
            if word.strip(".,!?;:\"()") not in stop_words
        ]

        if not important_words:
            return []

        conditions = " OR ".join(
            "LOWER(content) LIKE ?"
            for _ in important_words
        )

        parameters = [
            f"%{word}%"
            for word in important_words
        ]

        cursor.execute(
            f"""
            SELECT id, content, created_at
            FROM memories
            WHERE {conditions}
            ORDER BY id ASC
            """,
            parameters
        )

        return cursor.fetchall()

    def semantic_search_memories(self, query: str, limit: int = 5):
        query_embedding = self.embedding_provider.embed(query)

        cursor = self.connection.cursor()

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

    def delete_memory(self, memory_id: int):
        cursor = self.connection.cursor()

        cursor.execute(
            """
            DELETE FROM memories
            WHERE id = ?
            """,
            (memory_id,)
        )

        self.connection.commit()

        return cursor.rowcount > 0

    def update_memory(self, memory_id: int, content: str):
        embedding = self.embedding_provider.embed(content)
        embedding_json = json.dumps(embedding)

        cursor = self.connection.cursor()

        cursor.execute(
            """
            UPDATE memories
            SET content = ?, embedding = ?
            WHERE id = ?
            """,
            (content, embedding_json, memory_id)
        )

        self.connection.commit()

        return cursor.rowcount > 0

    def close(self):
        self.connection.close()