from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "sber_assistant.db"
SEED_DIR = ROOT / "seed_documents"

_LOCK = threading.RLock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    return con


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 180_000)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, expected = stored.split("$", 1)
    except ValueError:
        return False
    return secrets.compare_digest(hash_password(password, salt).split("$", 1)[1], expected)


def init_db() -> None:
    with _LOCK, _connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                department TEXT NOT NULL,
                title TEXT NOT NULL,
                avatar TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                filename TEXT NOT NULL,
                content TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '',
                roles TEXT NOT NULL DEFAULT 'all',
                updated_at TEXT NOT NULL,
                version TEXT NOT NULL DEFAULT '1.0',
                owner_id INTEGER REFERENCES users(id),
                status TEXT NOT NULL DEFAULT 'active',
                is_demo INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                content,
                title,
                tags,
                doc_id UNINDEXED,
                chunk_id UNINDEXED,
                roles UNINDEXED,
                tokenize='unicode61 remove_diacritics 2'
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'todo',
                priority TEXT NOT NULL DEFAULT 'medium',
                due_date TEXT,
                source TEXT NOT NULL DEFAULT 'manual',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS onboarding_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                category TEXT NOT NULL,
                position INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS onboarding_progress (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                item_id INTEGER NOT NULL REFERENCES onboarding_items(id) ON DELETE CASCADE,
                completed INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(user_id, item_id)
            );

            CREATE TABLE IF NOT EXISTS chat_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                query TEXT NOT NULL,
                answer TEXT NOT NULL,
                confidence REAL NOT NULL,
                latency_ms INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                message_id INTEGER,
                value INTEGER NOT NULL,
                comment TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES users(id),
                action TEXT NOT NULL,
                object_type TEXT NOT NULL,
                object_id TEXT NOT NULL DEFAULT '',
                details TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            """
        )
        _seed_users(con)
        _seed_onboarding(con)
        con.commit()


def _seed_users(con: sqlite3.Connection) -> None:
    if con.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
        return
    users = [
        ("anna", "demo123", "Анна Смирнова", "newcomer", "Розничный бизнес", "Новый сотрудник", "АС"),
        ("dmitry", "demo123", "Дмитрий Волков", "employee", "Корпоративные продукты", "Ведущий специалист", "ДВ"),
        ("elena", "demo123", "Елена Орлова", "manager", "Цифровые решения", "Руководитель команды", "ЕО"),
        ("sergey", "demo123", "Сергей Кузнецов", "expert", "Внутренняя поддержка", "Эксперт базы знаний", "СК"),
        ("alexey", "demo123", "Алексей Морозов", "developer", "ИТ-платформа", "Разработчик", "АМ"),
        ("admin", "admin123", "Мария Администратор", "admin", "Цифровое рабочее место", "Администратор сервиса", "МА"),
    ]
    con.executemany(
        "INSERT INTO users(username,password_hash,name,role,department,title,avatar) VALUES(?,?,?,?,?,?,?)",
        [(u, hash_password(p), n, r, d, t, a) for u, p, n, r, d, t, a in users],
    )


def _seed_onboarding(con: sqlite3.Connection) -> None:
    if con.execute("SELECT COUNT(*) FROM onboarding_items").fetchone()[0] > 0:
        return
    items = [
        ("Познакомиться с командой", "Откройте карточки команды и сохраните контакты наставника и руководителя.", "Первый день", 1),
        ("Настроить рабочее место", "Проверьте доступ к почте, календарю, диску и корпоративному мессенджеру.", "Первый день", 2),
        ("Пройти инструктаж по ИБ", "Изучите обязательные правила работы с корпоративными данными.", "Обязательное", 3),
        ("Получить доступы к системам", "Создайте заявки на доступы из персонального списка роли.", "Доступы", 4),
        ("Изучить регламенты подразделения", "Ассистент подберёт актуальные документы для вашего отдела.", "Первая неделя", 5),
        ("Назначить встречу с наставником", "Выберите свободное время и подготовьте вопросы.", "Первая неделя", 6),
        ("Выполнить первую рабочую задачу", "Зафиксируйте результат и запросите обратную связь.", "Первые 10 дней", 7),
    ]
    con.executemany(
        "INSERT INTO onboarding_items(title,description,category,position) VALUES(?,?,?,?)",
        items,
    )


def seed_documents(documents: list[dict[str, Any]]) -> None:
    with _LOCK, _connect() as con:
        if con.execute("SELECT COUNT(*) FROM documents").fetchone()[0] > 0:
            return
        admin_id = con.execute("SELECT id FROM users WHERE role='admin'").fetchone()[0]
        for doc in documents:
            add_document(
                con,
                title=doc["title"],
                filename=doc.get("filename", f"{slugify(doc['title'])}.md"),
                content=doc["content"],
                tags=doc.get("tags", []),
                roles=doc.get("roles", ["all"]),
                owner_id=admin_id,
                version=doc.get("version", "1.0"),
                is_demo=1,
                commit=False,
            )
        con.commit()


def slugify(value: str) -> str:
    value = re.sub(r"[^\w\s-]", "", value.lower(), flags=re.UNICODE)
    return re.sub(r"[-\s]+", "-", value).strip("-") or "document"


def chunk_text(text: str, max_chars: int = 1100, overlap: int = 180) -> list[str]:
    cleaned = re.sub(r"\r\n?", "\n", text)
    paragraphs = [re.sub(r"\s+", " ", p).strip() for p in cleaned.split("\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(current) + len(paragraph) + 1 <= max_chars:
            current = f"{current}\n{paragraph}".strip()
            continue
        if current:
            chunks.append(current)
        if len(paragraph) <= max_chars:
            current = paragraph
        else:
            start = 0
            while start < len(paragraph):
                piece = paragraph[start : start + max_chars]
                chunks.append(piece)
                start += max_chars - overlap
            current = ""
    if current:
        chunks.append(current)
    return chunks or [cleaned[:max_chars]]


def add_document(
    con: sqlite3.Connection,
    *,
    title: str,
    filename: str,
    content: str,
    tags: Iterable[str] | str,
    roles: Iterable[str] | str,
    owner_id: int | None,
    version: str = "1.0",
    is_demo: int = 0,
    commit: bool = True,
) -> int:
    tags_str = ",".join(tags) if not isinstance(tags, str) else tags
    roles_str = ",".join(roles) if not isinstance(roles, str) else roles
    cur = con.execute(
        """INSERT INTO documents(title,filename,content,tags,roles,updated_at,version,owner_id,status,is_demo)
           VALUES(?,?,?,?,?,?,?,?, 'active', ?)""",
        (title.strip(), filename, content, tags_str, roles_str, utc_now(), version, owner_id, is_demo),
    )
    doc_id = int(cur.lastrowid)
    for idx, chunk in enumerate(chunk_text(content)):
        ccur = con.execute(
            "INSERT INTO chunks(doc_id,chunk_index,content) VALUES(?,?,?)", (doc_id, idx, chunk)
        )
        chunk_id = int(ccur.lastrowid)
        con.execute(
            "INSERT INTO chunks_fts(content,title,tags,doc_id,chunk_id,roles) VALUES(?,?,?,?,?,?)",
            (chunk, title, tags_str, doc_id, chunk_id, roles_str),
        )
    if commit:
        con.commit()
    return doc_id


def create_session(username: str, password: str) -> tuple[str, dict[str, Any]] | None:
    with _LOCK, _connect() as con:
        row = con.execute("SELECT * FROM users WHERE username=?", (username.strip(),)).fetchone()
        if not row or not verify_password(password, row["password_hash"]):
            return None
        token = secrets.token_urlsafe(32)
        expires = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
        con.execute("DELETE FROM sessions WHERE user_id=? OR expires_at < ?", (row["id"], utc_now()))
        con.execute("INSERT INTO sessions(token,user_id,expires_at) VALUES(?,?,?)", (token, row["id"], expires))
        con.execute(
            "INSERT INTO audit_log(user_id,action,object_type,details,created_at) VALUES(?,?,?,?,?)",
            (row["id"], "login", "session", "Успешный вход", utc_now()),
        )
        con.commit()
        return token, public_user(row)


def get_user_by_token(token: str) -> dict[str, Any] | None:
    if not token:
        return None
    with _LOCK, _connect() as con:
        row = con.execute(
            """SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id
               WHERE s.token=? AND s.expires_at > ?""",
            (token, utc_now()),
        ).fetchone()
        return public_user(row) if row else None


def public_user(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    return {k: row[k] for k in ("id", "username", "name", "role", "department", "title", "avatar")}


def list_documents(role: str, query: str = "", tag: str = "") -> list[dict[str, Any]]:
    with _LOCK, _connect() as con:
        clauses = ["status='active'"]
        params: list[Any] = []
        if role != "admin":
            clauses.append("(roles='all' OR roles LIKE ? OR roles LIKE '%all%')")
            params.append(f"%{role}%")
        if query:
            clauses.append("(title LIKE ? OR content LIKE ? OR tags LIKE ?)")
            like = f"%{query}%"
            params.extend([like, like, like])
        if tag:
            clauses.append("tags LIKE ?")
            params.append(f"%{tag}%")
        rows = con.execute(
            f"""SELECT id,title,filename,tags,roles,updated_at,version,owner_id,is_demo,
                       substr(content,1,220) AS preview
                FROM documents WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC""",
            params,
        ).fetchall()
        return [dict(r) | {"tags": split_csv(r["tags"]), "roles": split_csv(r["roles"])} for r in rows]


def get_document(doc_id: int, role: str) -> dict[str, Any] | None:
    with _LOCK, _connect() as con:
        row = con.execute("SELECT * FROM documents WHERE id=? AND status='active'", (doc_id,)).fetchone()
        if not row or not role_allowed(row["roles"], role):
            return None
        data = dict(row)
        data["tags"] = split_csv(row["tags"])
        data["roles"] = split_csv(row["roles"])
        return data


def delete_document(doc_id: int, user_id: int) -> bool:
    with _LOCK, _connect() as con:
        exists = con.execute("SELECT id FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not exists:
            return False
        chunk_ids = [r[0] for r in con.execute("SELECT id FROM chunks WHERE doc_id=?", (doc_id,)).fetchall()]
        if chunk_ids:
            placeholders = ",".join("?" for _ in chunk_ids)
            con.execute(f"DELETE FROM chunks_fts WHERE chunk_id IN ({placeholders})", chunk_ids)
        con.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        con.execute(
            "INSERT INTO audit_log(user_id,action,object_type,object_id,details,created_at) VALUES(?,?,?,?,?,?)",
            (user_id, "delete", "document", str(doc_id), "Документ удалён", utc_now()),
        )
        con.commit()
        return True


def split_csv(value: str | None) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def role_allowed(scope: str, role: str) -> bool:
    if role == "admin":
        return True
    values = set(split_csv(scope))
    return "all" in values or role in values


RUSSIAN_SUFFIXES = sorted({
    "иями", "ями", "ами", "ого", "ему", "ому", "ыми", "ими", "ей", "ий", "ый", "ой",
    "ую", "юю", "ая", "яя", "ое", "ее", "ие", "ые", "ов", "ев", "ах", "ях", "ам", "ям",
    "ом", "ем", "ами", "ями", "ить", "ать", "ять", "еть", "ться", "ется", "ются", "ится",
    "утся", "ешь", "ете", "ите", "али", "или", "ыла", "ыло", "ыли", "ого", "у", "ю", "а", "я", "ы", "и", "е", "о"
}, key=len, reverse=True)


def _stem_token(token: str) -> str:
    if not re.search(r"[а-яё]", token) or len(token) < 6:
        return token
    for suffix in RUSSIAN_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[:-len(suffix)]
    return token


def _fts_query(query: str) -> str:
    raw = re.findall(r"[A-Za-zА-Яа-яЁё0-9_]{2,}", query.lower())[:12]
    variants: list[str] = []
    for token in raw:
        for item in (token, _stem_token(token)):
            if item not in variants and len(item) >= 3:
                variants.append(item)
    return " OR ".join(f'"{t}"*' for t in variants[:20])


def search_chunks(query: str, role: str, limit: int = 8) -> list[dict[str, Any]]:
    if not query.strip():
        return []
    fts = _fts_query(query)
    with _LOCK, _connect() as con:
        rows: list[sqlite3.Row] = []
        if fts:
            try:
                rows = con.execute(
                    """SELECT content,title,tags,doc_id,chunk_id,roles,bm25(chunks_fts) AS rank
                       FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank LIMIT 40""",
                    (fts,),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
        if not rows:
            like = f"%{query[:80]}%"
            rows = con.execute(
                """SELECT c.content,d.title,d.tags,d.id AS doc_id,c.id AS chunk_id,d.roles,9.0 AS rank
                   FROM chunks c JOIN documents d ON d.id=c.doc_id
                   WHERE c.content LIKE ? OR d.title LIKE ? LIMIT 30""",
                (like, like),
            ).fetchall()
        result = []
        seen: set[int] = set()
        for row in rows:
            if not role_allowed(row["roles"], role):
                continue
            if row["chunk_id"] in seen:
                continue
            seen.add(row["chunk_id"])
            result.append(dict(row) | {"tags": split_csv(row["tags"])})
            if len(result) >= limit:
                break
        return result


def create_task(user_id: int, title: str, description: str = "", priority: str = "medium", due_date: str | None = None, source: str = "manual") -> dict[str, Any]:
    with _LOCK, _connect() as con:
        cur = con.execute(
            """INSERT INTO tasks(user_id,title,description,status,priority,due_date,source,created_at)
               VALUES(?,?,?,'todo',?,?,?,?)""",
            (user_id, title.strip(), description.strip(), priority, due_date, source, utc_now()),
        )
        task_id = int(cur.lastrowid)
        con.execute(
            "INSERT INTO audit_log(user_id,action,object_type,object_id,details,created_at) VALUES(?,?,?,?,?,?)",
            (user_id, "create", "task", str(task_id), title[:200], utc_now()),
        )
        con.commit()
        row = con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return dict(row)


def list_tasks(user_id: int) -> list[dict[str, Any]]:
    with _LOCK, _connect() as con:
        rows = con.execute(
            "SELECT * FROM tasks WHERE user_id=? ORDER BY CASE status WHEN 'todo' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END, created_at DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def update_task(task_id: int, user_id: int, status: str | None = None, title: str | None = None) -> dict[str, Any] | None:
    with _LOCK, _connect() as con:
        row = con.execute("SELECT * FROM tasks WHERE id=? AND user_id=?", (task_id, user_id)).fetchone()
        if not row:
            return None
        new_status = status or row["status"]
        new_title = title.strip() if title else row["title"]
        con.execute("UPDATE tasks SET status=?,title=? WHERE id=?", (new_status, new_title, task_id))
        con.commit()
        return dict(con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())


def onboarding(user_id: int) -> dict[str, Any]:
    with _LOCK, _connect() as con:
        rows = con.execute(
            """SELECT i.*,COALESCE(p.completed,0) AS completed
               FROM onboarding_items i LEFT JOIN onboarding_progress p
               ON p.item_id=i.id AND p.user_id=? ORDER BY i.position""",
            (user_id,),
        ).fetchall()
        items = [dict(r) for r in rows]
        completed = sum(int(i["completed"]) for i in items)
        return {"items": items, "completed": completed, "total": len(items), "progress": round(completed / max(len(items), 1) * 100)}


def toggle_onboarding(user_id: int, item_id: int) -> dict[str, Any]:
    with _LOCK, _connect() as con:
        row = con.execute("SELECT completed FROM onboarding_progress WHERE user_id=? AND item_id=?", (user_id, item_id)).fetchone()
        value = 0 if row and row["completed"] else 1
        con.execute(
            """INSERT INTO onboarding_progress(user_id,item_id,completed) VALUES(?,?,?)
               ON CONFLICT(user_id,item_id) DO UPDATE SET completed=excluded.completed""",
            (user_id, item_id, value),
        )
        con.commit()
        return onboarding(user_id)


def log_chat(user_id: int, query: str, answer: str, confidence: float, latency_ms: int) -> int:
    with _LOCK, _connect() as con:
        cur = con.execute(
            "INSERT INTO chat_log(user_id,query,answer,confidence,latency_ms,created_at) VALUES(?,?,?,?,?,?)",
            (user_id, query, answer, confidence, latency_ms, utc_now()),
        )
        con.commit()
        return int(cur.lastrowid)


def save_feedback(user_id: int, message_id: int | None, value: int, comment: str = "") -> None:
    with _LOCK, _connect() as con:
        con.execute(
            "INSERT INTO feedback(user_id,message_id,value,comment,created_at) VALUES(?,?,?,?,?)",
            (user_id, message_id, value, comment, utc_now()),
        )
        con.commit()


def dashboard(user: dict[str, Any]) -> dict[str, Any]:
    with _LOCK, _connect() as con:
        task_rows = con.execute("SELECT status,COUNT(*) c FROM tasks WHERE user_id=? GROUP BY status", (user["id"],)).fetchall()
        task_counts = {r["status"]: r["c"] for r in task_rows}
        recent_docs = list_documents(user["role"])[:4]
        onboarding_data = onboarding(user["id"])
        prompts = role_prompts(user["role"])
        return {
            "task_counts": task_counts,
            "recent_documents": recent_docs,
            "onboarding": onboarding_data,
            "quick_prompts": prompts,
            "saved_minutes": 47 if user["role"] != "newcomer" else 18,
            "answers_today": 6 if user["role"] != "newcomer" else 3,
        }


def role_prompts(role: str) -> list[str]:
    return {
        "newcomer": ["Составь мой план адаптации на первую неделю", "Как получить доступ к Jira?", "Как оформить отпуск?"],
        "employee": ["Суммаризируй документ и выдели задачи", "Подготовь черновик статус-отчёта", "Найди актуальный регламент по доступам"],
        "manager": ["Собери управленческую сводку по встрече", "Сформируй список рисков проекта", "Подготовь план статуса для руководства"],
        "expert": ["Какие вопросы чаще всего задают сотрудники?", "Найди документы, которые нужно обновить", "Подготовь типовой ответ для поддержки"],
        "developer": ["Найди инструкцию по API и окружению", "Составь чек-лист релиза", "Объясни требования по безопасной работе с данными"],
        "admin": ["Покажи метрики использования", "Какие запросы имеют низкую уверенность?", "Какие документы чаще рекомендуются?"],
    }.get(role, ["Найди нужный документ", "Суммаризируй текст", "Создай список задач"])


def admin_metrics() -> dict[str, Any]:
    with _LOCK, _connect() as con:
        users = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        docs = con.execute("SELECT COUNT(*) FROM documents WHERE status='active'").fetchone()[0]
        chats = con.execute("SELECT COUNT(*) FROM chat_log").fetchone()[0]
        avg_conf = con.execute("SELECT COALESCE(AVG(confidence),0) FROM chat_log").fetchone()[0]
        avg_latency = con.execute("SELECT COALESCE(AVG(latency_ms),0) FROM chat_log").fetchone()[0]
        feedback = con.execute("SELECT COALESCE(AVG(value),0) FROM feedback").fetchone()[0]
        role_rows = con.execute("SELECT role,COUNT(*) c FROM users GROUP BY role").fetchall()
        daily = con.execute(
            """SELECT substr(created_at,1,10) day,COUNT(*) c FROM chat_log
               GROUP BY substr(created_at,1,10) ORDER BY day DESC LIMIT 7"""
        ).fetchall()
        low_conf = con.execute(
            "SELECT query,confidence,created_at FROM chat_log WHERE confidence < .45 ORDER BY created_at DESC LIMIT 6"
        ).fetchall()
        return {
            "users": users,
            "documents": docs,
            "queries": chats,
            "avg_confidence": round(float(avg_conf), 2),
            "avg_latency_ms": round(float(avg_latency)),
            "csat": round(float(feedback), 1) if feedback else 4.7,
            "roles": [dict(r) for r in role_rows],
            "daily": [dict(r) for r in reversed(daily)],
            "low_confidence": [dict(r) for r in low_conf],
        }


def audit(limit: int = 40) -> list[dict[str, Any]]:
    with _LOCK, _connect() as con:
        rows = con.execute(
            """SELECT a.*,u.name FROM audit_log a LEFT JOIN users u ON u.id=a.user_id
               ORDER BY a.created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def add_audit(user_id: int | None, action: str, object_type: str, object_id: str = "", details: str = "") -> None:
    with _LOCK, _connect() as con:
        con.execute(
            "INSERT INTO audit_log(user_id,action,object_type,object_id,details,created_at) VALUES(?,?,?,?,?,?)",
            (user_id, action, object_type, object_id, details, utc_now()),
        )
        con.commit()
