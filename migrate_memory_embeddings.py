import json

from memory.database import Database


database = Database()

memories = database.get_memories()

updated = 0

for memory_id, content, created_at in memories:
    cursor = database.connection.cursor()

    cursor.execute(
        "SELECT embedding FROM memories WHERE id = ?",
        (memory_id,)
    )

    embedding_json = cursor.fetchone()[0]

    if embedding_json is not None:
        continue

    embedding = database.embedding_provider.embed(content)

    embedding_json = json.dumps(embedding)

    cursor.execute(
        """
        UPDATE memories
        SET embedding = ?
        WHERE id = ?
        """,
        (embedding_json, memory_id)
    )

    updated += 1

database.connection.commit()

print(f"Обновлено воспоминаний: {updated}")

database.close()