from app.database.mongo import get_db

db = get_db()
db.test.insert_one({"status": "MongoDB connected successfully"})

print("OK")
