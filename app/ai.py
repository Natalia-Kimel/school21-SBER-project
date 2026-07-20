from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

import httpx

from . import db

STOPWORDS = {
    "как", "что", "это", "для", "или", "при", "над", "под", "где", "когда", "какой", "какая", "какие",
    "мне", "мой", "моя", "мои", "нужно", "можно", "найди", "покажи", "сделай", "составь", "про", "по", "из",
    "на", "в", "во", "и", "а", "но", "не", "бы", "с", "со", "у", "к", "ко", "от", "до", "же", "ли",
}


@dataclass
class Answer:
    text: str
    sources: list[dict[str, Any]]
    suggestions: list[str]
    confidence: float
    mode: str


def tokens(text: str) -> list[str]:
    result = []
    for token in re.findall(r"[A-Za-zА-Яа-яЁё0-9_]{2,}", text):
        token = token.lower()
        if token in STOPWORDS:
            continue
        result.append(db._stem_token(token))
    return result


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [re.sub(r"\s+", " ", p).strip(" -•\t") for p in parts if len(p.strip()) > 24]


def _rank_sentences(query: str, chunks: list[dict[str, Any]], limit: int = 6) -> list[str]:
    q = set(tokens(query))
    candidates: list[tuple[float, str]] = []
    for pos, chunk in enumerate(chunks):
        for sent in sentences(chunk["content"]):
            st = set(tokens(sent))
            if not st:
                continue
            overlap = len(q & st) / max(len(q), 1)
            specificity = min(len(st), 24) / 24
            score = overlap * 3 + specificity * .25 + 1 / (pos + 2)
            candidates.append((score, sent))
    candidates.sort(key=lambda x: x[0], reverse=True)
    selected: list[str] = []
    seen = set()
    for _, sent in candidates:
        key = re.sub(r"\W+", "", sent.lower())[:80]
        if key in seen:
            continue
        seen.add(key)
        selected.append(sent)
        if len(selected) >= limit:
            break
    return selected


def _confidence(query: str, chunks: list[dict[str, Any]]) -> float:
    if not chunks:
        return 0.18
    q = set(tokens(query))
    top = set(tokens(" ".join(c["content"] for c in chunks[:3])))
    overlap = len(q & top) / max(len(q), 1)
    doc_bonus = min(len({c["doc_id"] for c in chunks}), 3) * .05
    return round(min(.96, .38 + overlap * .48 + doc_bonus), 2)


def _source_cards(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    seen = set()
    for c in chunks:
        if c["doc_id"] in seen:
            continue
        seen.add(c["doc_id"])
        excerpt = re.sub(r"\s+", " ", c["content"]).strip()[:240]
        result.append({
            "id": c["doc_id"],
            "title": c["title"],
            "excerpt": excerpt + ("…" if len(c["content"]) > 240 else ""),
            "tags": c.get("tags", []),
        })
        if len(result) >= 4:
            break
    return result


def _local_answer(query: str, role: str, chunks: list[dict[str, Any]]) -> Answer:
    conf = _confidence(query, chunks)
    source_cards = _source_cards(chunks)
    if not chunks:
        return Answer(
            text=(
                "В доступной вам базе знаний я не нашёл надёжного ответа. "
                "Попробуйте уточнить название процесса, системы или подразделения. "
                "Для критичного вопроса лучше создать обращение эксперту — я сохраню контекст запроса."
            ),
            sources=[],
            suggestions=["Уточнить запрос", "Открыть базу знаний", "Передать вопрос эксперту"],
            confidence=conf,
            mode="local-rag",
        )

    qlow = query.lower()
    is_instruction = any(w in qlow for w in ("как", "инструк", "оформ", "получить", "доступ"))
    if is_instruction and chunks:
        primary_doc = chunks[0]["doc_id"]
        primary_chunks = [c for c in chunks if c["doc_id"] == primary_doc]
        selected = _rank_sentences(query, primary_chunks, limit=6)
        if len(selected) < 3:
            selected += [s for s in _rank_sentences(query, chunks, limit=6) if s not in selected]
    else:
        selected = _rank_sentences(query, chunks)
    intro = "По документам, доступным для вашей роли,"
    if is_instruction:
        bullets = selected[:5]
        text = f"{intro} рекомендованный порядок действий:\n\n" + "\n".join(f"{i+1}. {s}" for i, s in enumerate(bullets))
        text += "\n\nПеред выполнением проверьте дату и версию документа в источниках ниже."
    elif any(w in qlow for w in ("суммар", "кратко", "вывод", "итог")):
        text = f"{intro} ключевые выводы:\n\n" + "\n".join(f"• {s}" for s in selected[:5])
    elif any(w in qlow for w in ("риск", "безопас", "152", "утеч")):
        text = f"{intro} важны следующие требования и ограничения:\n\n" + "\n".join(f"• {s}" for s in selected[:5])
        text += "\n\nДействия с данными и внешними системами должны выполняться только в пределах ваших прав доступа."
    else:
        text = f"{intro} нашлась следующая информация:\n\n" + "\n".join(f"• {s}" for s in selected[:5])
        text += "\n\nЯ также подобрал наиболее подходящие документы — они показаны под ответом."

    suggestions = ["Показать пошаговую инструкцию", "Сравнить версии документов", "Создать задачу по ответу"]
    return Answer(text=text, sources=source_cards, suggestions=suggestions, confidence=conf, mode="local-rag")


async def _llm_answer(query: str, role: str, chunks: list[dict[str, Any]]) -> str | None:
    provider = os.getenv("LLM_PROVIDER", "local").lower()
    if provider not in {"openai_compatible", "gateway"}:
        return None
    endpoint = os.getenv("LLM_API_URL", "").strip()
    api_key = os.getenv("LLM_API_KEY", "").strip()
    model = os.getenv("LLM_MODEL", "").strip() or "corporate-assistant"
    if not endpoint:
        return None
    context = []
    for i, c in enumerate(chunks[:6], 1):
        context.append(f"[{i}] {c['title']}\n{c['content']}")
    system = (
        "Ты корпоративный ИИ-ассистент сотрудника. Отвечай только на основании переданного контекста. "
        "Не выдумывай регламенты и факты. Если данных недостаточно, прямо скажи об этом. "
        "Давай понятный ответ на русском языке, учитывай роль пользователя, а после утверждений ставь ссылки [1], [2]. "
        "Для действий с риском проси подтверждение."
    )
    payload = {
        "model": model,
        "temperature": 0.15,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Роль: {role}\n\nКонтекст:\n{'\n\n'.join(context)}\n\nЗапрос: {query}"},
        ],
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=45, verify=os.getenv("LLM_VERIFY_SSL", "true").lower() != "false") as client:
            response = await client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


async def answer_query(query: str, role: str) -> Answer:
    chunks = db.search_chunks(query, role, 8)
    local = _local_answer(query, role, chunks)
    generated = await _llm_answer(query, role, chunks)
    if generated:
        return Answer(
            text=generated,
            sources=local.sources,
            suggestions=local.suggestions,
            confidence=local.confidence,
            mode="generative-rag",
        )
    return local


def summarize_meeting(text: str) -> dict[str, Any]:
    sents = sentences(text)
    if not sents:
        return {"summary": "Недостаточно текста для суммаризации.", "decisions": [], "tasks": [], "risks": []}
    keywords = Counter(tokens(text))
    top_words = {w for w, _ in keywords.most_common(12)}
    scored = sorted(
        ((len(set(tokens(s)) & top_words) + min(len(s), 220) / 220, idx, s) for idx, s in enumerate(sents)),
        reverse=True,
    )
    summary = [s for _, _, s in sorted(scored[:4], key=lambda x: x[1])]
    decisions = [s for s in sents if re.search(r"\b(решили|договорились|согласовали|утвердили|принято)\b", s, re.I)][:5]
    risks = [s for s in sents if re.search(r"\b(риск|проблем|блокер|задерж|не успе|опасен)\w*", s, re.I)][:4]
    task_candidates = [s for s in sents if re.search(r"\b(нужно|необходимо|подготовит|сделает|проверит|отправит|создать|срок|до \d)\w*", s, re.I)][:6]
    tasks = []
    for s in task_candidates:
        due = None
        m = re.search(r"до\s+(\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?)", s, re.I)
        if m:
            due = m.group(1)
        tasks.append({"title": s[:180], "due_date": due, "priority": "medium"})
    return {
        "summary": " ".join(summary),
        "decisions": decisions or ["Явно сформулированные решения не обнаружены."],
        "tasks": tasks,
        "risks": risks,
    }


def analyze_document(text: str, role: str) -> dict[str, Any]:
    sents = sentences(text)
    freq = Counter(tokens(text))
    keywords = [w for w, _ in freq.most_common(10)]
    top = sorted(
        ((sum(freq[t] for t in set(tokens(s))), idx, s) for idx, s in enumerate(sents)),
        reverse=True,
    )[:5]
    summary_sents = [s for _, idx, s in sorted(top, key=lambda x: x[1])]
    related_query = " ".join(keywords[:6])
    related = _source_cards(db.search_chunks(related_query, role, 6)) if related_query else []
    numeric = re.findall(r"\b\d+(?:[.,]\d+)?\s*%?\b", text)
    return {
        "summary": " ".join(summary_sents) if summary_sents else text[:800],
        "keywords": keywords,
        "facts": numeric[:12],
        "related_documents": related,
        "characters": len(text),
        "paragraphs": len([p for p in text.splitlines() if p.strip()]),
    }
