from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import ai, db
from .parsers import clean_text, extract_text

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

app = FastAPI(title="СберАссистент MVP", version="1.0.0")


class LoginRequest(BaseModel):
    username: str
    password: str


class ChatRequest(BaseModel):
    query: str = Field(min_length=2, max_length=4000)


class TaskRequest(BaseModel):
    title: str = Field(min_length=2, max_length=240)
    description: str = ""
    priority: str = "medium"
    due_date: str | None = None
    source: str = "manual"


class TaskUpdate(BaseModel):
    status: str | None = None
    title: str | None = None


class MeetingRequest(BaseModel):
    transcript: str = Field(min_length=10)
    create_tasks: bool = False


class FeedbackRequest(BaseModel):
    message_id: int | None = None
    value: int = Field(ge=1, le=5)
    comment: str = ""


def current_user(authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    user = db.get_user_by_token(token)
    if not user:
        raise HTTPException(401, "Сессия недействительна. Войдите снова.")
    return user


def require_roles(*roles: str):
    def dep(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        if user["role"] not in roles:
            raise HTTPException(403, "Недостаточно прав")
        return user
    return dep


@app.on_event("startup")
def startup() -> None:
    db.init_db()
    seed_path = ROOT / "seed_documents" / "seed.json"
    if seed_path.exists():
        db.seed_documents(json.loads(seed_path.read_text(encoding="utf-8")))


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "СберАссистент", "ai_mode": os.getenv("LLM_PROVIDER", "local")}


@app.post("/api/login")
def login(payload: LoginRequest) -> dict[str, Any]:
    result = db.create_session(payload.username, payload.password)
    if not result:
        raise HTTPException(401, "Неверный логин или пароль")
    token, user = result
    return {"token": token, "user": user}


@app.get("/api/me")
def me(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return user


@app.get("/api/dashboard")
def get_dashboard(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return db.dashboard(user)


@app.post("/api/chat")
async def chat(payload: ChatRequest, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    start = time.perf_counter()
    answer = await ai.answer_query(payload.query, user["role"])
    latency_ms = int((time.perf_counter() - start) * 1000)
    message_id = db.log_chat(user["id"], payload.query, answer.text, answer.confidence, latency_ms)
    return {
        "message_id": message_id,
        "answer": answer.text,
        "sources": answer.sources,
        "suggestions": answer.suggestions,
        "confidence": answer.confidence,
        "latency_ms": latency_ms,
        "mode": answer.mode,
    }


@app.post("/api/feedback")
def feedback(payload: FeedbackRequest, user: dict[str, Any] = Depends(current_user)) -> dict[str, bool]:
    db.save_feedback(user["id"], payload.message_id, payload.value, payload.comment)
    return {"ok": True}


@app.get("/api/knowledge")
def knowledge(query: str = "", tag: str = "", user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    return db.list_documents(user["role"], query, tag)


@app.get("/api/knowledge/{doc_id}")
def knowledge_item(doc_id: int, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    doc = db.get_document(doc_id, user["role"])
    if not doc:
        raise HTTPException(404, "Документ не найден или недоступен")
    db.add_audit(user["id"], "read", "document", str(doc_id), doc["title"])
    return doc


@app.post("/api/knowledge/upload")
async def upload_knowledge(
    title: Annotated[str, Form()],
    tags: Annotated[str, Form()] = "",
    roles: Annotated[str, Form()] = "all",
    version: Annotated[str, Form()] = "1.0",
    file: UploadFile = File(...),
    user: dict[str, Any] = Depends(require_roles("expert", "admin")),
) -> dict[str, Any]:
    raw = await file.read()
    if len(raw) > 12 * 1024 * 1024:
        raise HTTPException(413, "Файл больше 12 МБ")
    try:
        text = clean_text(extract_text(file.filename or "document.txt", raw))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if len(text) < 30:
        raise HTTPException(400, "Не удалось извлечь достаточно текста")
    with db._LOCK, db._connect() as con:
        doc_id = db.add_document(
            con,
            title=title,
            filename=file.filename or "document",
            content=text,
            tags=[t.strip() for t in tags.split(",") if t.strip()],
            roles=[r.strip() for r in roles.split(",") if r.strip()] or ["all"],
            owner_id=user["id"],
            version=version,
        )
    db.add_audit(user["id"], "upload", "document", str(doc_id), title)
    return {"id": doc_id, "title": title, "chunks": len(db.chunk_text(text))}


@app.delete("/api/knowledge/{doc_id}")
def remove_knowledge(doc_id: int, user: dict[str, Any] = Depends(require_roles("expert", "admin"))) -> dict[str, bool]:
    if not db.delete_document(doc_id, user["id"]):
        raise HTTPException(404, "Документ не найден")
    return {"ok": True}


@app.get("/api/tasks")
def tasks(user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    return db.list_tasks(user["id"])


@app.post("/api/tasks")
def add_task(payload: TaskRequest, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return db.create_task(user["id"], payload.title, payload.description, payload.priority, payload.due_date, payload.source)


@app.patch("/api/tasks/{task_id}")
def patch_task(task_id: int, payload: TaskUpdate, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    result = db.update_task(task_id, user["id"], payload.status, payload.title)
    if not result:
        raise HTTPException(404, "Задача не найдена")
    return result


@app.get("/api/onboarding")
def get_onboarding(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return db.onboarding(user["id"])


@app.post("/api/onboarding/{item_id}/toggle")
def toggle_onboarding(item_id: int, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return db.toggle_onboarding(user["id"], item_id)


@app.post("/api/meetings/summarize")
def meeting_summary(payload: MeetingRequest, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    result = ai.summarize_meeting(payload.transcript)
    created = []
    if payload.create_tasks:
        for task in result["tasks"][:5]:
            created.append(db.create_task(user["id"], task["title"], source="meeting", due_date=task.get("due_date")))
    db.add_audit(user["id"], "summarize", "meeting", details=f"Создано задач: {len(created)}")
    result["created_tasks"] = created
    return result


@app.post("/api/documents/analyze")
async def analyze_file(file: UploadFile = File(...), user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    raw = await file.read()
    if len(raw) > 12 * 1024 * 1024:
        raise HTTPException(413, "Файл больше 12 МБ")
    try:
        text = clean_text(extract_text(file.filename or "document.txt", raw))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    result = ai.analyze_document(text, user["role"])
    result["filename"] = file.filename
    db.add_audit(user["id"], "analyze", "file", details=file.filename or "")
    return result


@app.get("/api/admin/metrics")
def metrics(user: dict[str, Any] = Depends(require_roles("admin", "manager"))) -> dict[str, Any]:
    return db.admin_metrics()


@app.get("/api/admin/audit")
def audit(user: dict[str, Any] = Depends(require_roles("admin"))) -> list[dict[str, Any]]:
    return db.audit()


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/{path:path}")
def spa(path: str) -> FileResponse:
    candidate = STATIC / path
    if candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(STATIC / "index.html")
