"""
CF Compare v2 — Backend API (with authentication)
FastAPI application with:
  - User registration / login (JWT)
  - Codeforces user comparison
  - DB caching (10-minute window)
  - Rating history & tag analysis
  - Per-user comparison history
  - Optional LLM-powered insights
"""

import os
import re
import json
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from collections import Counter

import httpx
from fastapi import FastAPI, HTTPException, Query, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, Text, DateTime, func, JSON, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
import jwt  # PyJWT

# ─── JWT & Password Config ───────────────────────────────────────────────

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 72  # token lives 3 days

import bcrypt


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())

# ─── Database Setup ───────────────────────────────────────────────────────

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://cfuser:cfpassword@db:5432/cfcompare"
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Cache window (seconds)
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "600"))  # 10 min


# ─── SQLAlchemy Models ────────────────────────────────────────────────────

class CFUser(Base):
    """Authenticated app user."""
    __tablename__ = "cf_users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(Text, unique=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CFHandle(Base):
    """Catalog of all unique CF handles ever compared."""
    __tablename__ = "cf_handles"
    id = Column(Integer, primary_key=True, index=True)
    handle = Column(Text, unique=True, nullable=False)
    first_seen = Column(DateTime(timezone=True), server_default=func.now())


class ComparisonModel(Base):
    """One comparison session — tied to an authenticated user."""
    __tablename__ = "comparisons"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False)  # FK to cf_users
    handles = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ComparisonResultModel(Base):
    """Per-user stats for one comparison."""
    __tablename__ = "comparison_results"
    id = Column(Integer, primary_key=True, index=True)
    comparison_id = Column(Integer, nullable=False)
    handle = Column(Text, nullable=False)
    rating = Column(Integer, nullable=True)
    rank = Column(Text, nullable=True)
    max_rating = Column(Integer, nullable=True)
    max_rank = Column(Text, nullable=True)
    solved_count = Column(Integer, default=0)
    rating_history = Column(JSON, default=list)
    tag_stats = Column(JSON, default=dict)


class InsightModel(Base):
    """LLM-generated insight."""
    __tablename__ = "insights"
    id = Column(Integer, primary_key=True, index=True)
    comparison_id = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


Base.metadata.create_all(bind=engine)


# ─── FastAPI App ──────────────────────────────────────────────────────────

app = FastAPI(title="CF Compare API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Codeforces API ───────────────────────────────────────────────────────

API_KEY = os.getenv("API_KEY", "")
API_SECRET = os.getenv("API_SECRET", "")
CF_API = "https://codeforces.com/api"


async def cf_request(method: str, params: dict) -> dict:
    """Proxy to Codeforces public API."""
    url = f"{CF_API}/{method}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, params=params)
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code,
                                detail=f"Codeforces API error: {resp.text}")
        data = resp.json()
        if data.get("status") != "OK":
            raise HTTPException(status_code=400,
                                detail=f"CF API: {data.get('comment', 'Unknown')}")
        return data["result"]


# ─── Data Analysis ────────────────────────────────────────────────────────

def compute_tag_stats(submissions: list) -> dict:
    """Count solved problems per tag (unique problems only, verdict=OK)."""
    solved = {}
    for sub in submissions:
        if sub.get("verdict") != "OK" or "problem" not in sub:
            continue
        p = sub["problem"]
        key = (p.get("contestId"), p.get("index"))
        if key not in solved:
            solved[key] = p.get("tags", [])
    counter: Counter = Counter()
    for tags in solved.values():
        for t in tags:
            counter[t] += 1
    return dict(counter.most_common(20))


def format_rating_history(history: list) -> list:
    """Keep only useful fields from rating history."""
    return [
        {
            "contest_name": h.get("contestName", ""),
            "old_rating": h.get("oldRating", 0),
            "new_rating": h.get("newRating", 0),
            "rank": h.get("rank", ""),
        }
        for h in history
    ]


# ─── Pydantic Models ─────────────────────────────────────────────────────

class RegisterReq(BaseModel):
    username: str
    password: str


class LoginReq(BaseModel):
    username: str
    password: str


class TokenRes(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


class UserStats(BaseModel):
    handle: str
    rating: Optional[int] = None
    rank: Optional[str] = None
    max_rating: Optional[int] = None
    max_rank: Optional[str] = None
    solved_count: int = 0
    rating_history: list = []
    tag_stats: dict = {}
    found: bool = True
    error: Optional[str] = None


class ComparisonPayload(BaseModel):
    users: List[UserStats]
    cached: bool = False
    comparison_id: Optional[int] = None


class HistoryEntry(BaseModel):
    id: int
    handles: str
    created_at: Optional[str] = None
    users: List[UserStats]


class InsightPayload(BaseModel):
    comparison_id: int
    content: str


# ─── Auth Helpers ─────────────────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_jwt(user_id: int, username: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS)
    return jwt.encode({"sub": user_id, "username": username, "exp": exp},
                      JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_jwt(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


async def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> CFUser:
    """
    Extract JWT from Authorization header or cookie.
    Raises 401 if invalid or missing.
    """
    token = None

    # 1. Check Authorization header
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]

    # 2. Fallback: cookie
    if not token:
        token = request.cookies.get("cf_token")

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = decode_jwt(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(CFUser).filter(CFUser.id == payload["sub"]).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def _normalized_handles(handles: str) -> str:
    """Sort handles so 'a,b' and 'b,a' produce the same key."""
    return ",".join(sorted(h.strip().lower() for h in handles.split(",") if h.strip()))


# ─── Cache & DB Helpers ──────────────────────────────────────────────────

def check_cache(db: Session, user_id: int, norm_handles: str) -> Optional[dict]:
    """Return cached comparison for this user within TTL."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=CACHE_TTL_SECONDS)
    comp = (
        db.query(ComparisonModel)
        .filter(
            ComparisonModel.user_id == user_id,
            ComparisonModel.handles == norm_handles,
            ComparisonModel.created_at >= cutoff,
        )
        .order_by(ComparisonModel.created_at.desc())
        .first()
    )
    if not comp:
        return None

    results = db.query(ComparisonResultModel).filter(
        ComparisonResultModel.comparison_id == comp.id
    ).all()

    users = [UserStats(
        handle=r.handle, rating=r.rating, rank=r.rank,
        max_rating=r.max_rating, max_rank=r.max_rank,
        solved_count=r.solved_count,
        rating_history=r.rating_history or [],
        tag_stats=r.tag_stats or {},
    ) for r in results]

    return {"users": users, "cached": True, "comparison_id": comp.id}


def save_comparison(db: Session, user_id: int, norm_handles: str, users_data: list) -> int:
    """Persist comparison + ensure handles exist in cf_handles."""
    for u in users_data:
        if not db.query(CFHandle).filter(CFHandle.handle == u["handle"]).first():
            db.add(CFHandle(handle=u["handle"]))
    db.flush()

    comp = ComparisonModel(user_id=user_id, handles=norm_handles)
    db.add(comp)
    db.flush()

    for u in users_data:
        db.add(ComparisonResultModel(
            comparison_id=comp.id,
            handle=u["handle"],
            rating=u.get("rating"),
            rank=u.get("rank"),
            max_rating=u.get("max_rating"),
            max_rank=u.get("max_rank"),
            solved_count=u.get("solved_count", 0),
            rating_history=u.get("rating_history", []),
            tag_stats=u.get("tag_stats", {}),
        ))
    db.commit()
    return comp.id


# ─── LLM Integration ─────────────────────────────────────────────────────

LLM_API_URL = os.getenv("LLM_API_URL", "")
LLM_MODEL = os.getenv("LLM_MODEL", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")


def _build_prompt(users: list) -> str:
    lines = ["Compare these competitive programmers and give short, actionable insights.\n"]
    for u in users:
        top_tags = ", ".join(
            f"{k}:{v}" for k, v in
            sorted((u.get("tag_stats") or {}).items(), key=lambda x: x[1], reverse=True)[:3]
        )
        lines.append(
            f"- {u['handle']}: rating {u.get('rating', 'N/A')}, "
            f"solved {u.get('solved_count', 0)}, top tags: {top_tags or 'none'}"
        )
    lines.append("\nOutput only 2-4 bullet points. Be specific.")
    return "\n".join(lines)


async def _call_llm(prompt: str) -> str:
    """Try OpenAI → Ollama → rule-based fallback."""
    if LLM_API_URL and LLM_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=30.0) as c:
                r = await c.post(
                    f"{LLM_API_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"},
                    json={"model": LLM_MODEL or "gpt-3.5-turbo",
                          "messages": [{"role": "user", "content": prompt}], "max_tokens": 300},
                )
                if r.status_code == 200:
                    return r.json()["choices"][0]["message"]["content"]
        except Exception:
            pass

    if LLM_API_URL and "/api/generate" in LLM_API_URL:
        try:
            async with httpx.AsyncClient(timeout=30.0) as c:
                r = await c.post(
                    LLM_API_URL,
                    json={"model": LLM_MODEL or "llama3", "prompt": prompt, "stream": False},
                )
                if r.status_code == 200:
                    return r.json().get("response", "")
        except Exception:
            pass

    return _rule_based_insight(prompt)


def _rule_based_insight(prompt: str) -> str:
    """Simple insight without external LLM."""
    lines = []
    matches = re.findall(
        r"- (\w+): rating (\d+), solved (\d+), top tags: (.+)", prompt
    )
    if len(matches) >= 2:
        best = max(matches, key=lambda m: int(m[1]))
        lines.append(f"🏆 **{best[0]}** has the highest rating ({best[1]}).")
        most = max(matches, key=lambda m: int(m[2]))
        if most[0] != best[0]:
            lines.append(f"📚 **{most[0]}** solved the most problems ({most[2]}).")
        for handle, rating, solved, tags in matches:
            if tags and tags != "none":
                lines.append(f"💡 **{handle}** is strongest in *{tags.split(':')[0].strip()}* problems.")
    if not lines:
        lines.append("Not enough data to generate insights.")
    return "\n".join(lines)


# ─── Auth Endpoints ───────────────────────────────────────────────────────

@app.post("/auth/register", response_model=TokenRes)
async def register(req: RegisterReq, db: Session = Depends(get_db)):
    """Create a new user account and return JWT."""
    if len(req.username) < 3:
        raise HTTPException(status_code=400, detail="Username must be ≥ 3 characters")
    if len(req.password) < 4:
        raise HTTPException(status_code=400, detail="Password must be ≥ 4 characters")

    existing = db.query(CFUser).filter(CFUser.username == req.username).first()
    if existing:
        raise HTTPException(status_code=409, detail="Username already exists")

    user = CFUser(username=req.username, password_hash=hash_password(req.password))
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_jwt(user.id, user.username)
    return TokenRes(access_token=token, username=user.username)


@app.post("/auth/login", response_model=TokenRes)
async def login(req: LoginReq, db: Session = Depends(get_db)):
    """Authenticate and return JWT."""
    user = db.query(CFUser).filter(CFUser.username == req.username).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_jwt(user.id, user.username)
    return TokenRes(access_token=token, username=user.username)


@app.get("/auth/me")
async def me(user: CFUser = Depends(get_current_user)):
    """Get current authenticated user info."""
    return {"id": user.id, "username": user.username, "created_at": user.created_at.isoformat() if user.created_at else None}


# ─── Comparison Endpoints (auth required) ─────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}


@app.get("/compare", response_model=ComparisonPayload)
async def compare_users(
    handles: str = Query(..., min_length=1),
    user: CFUser = Depends(get_current_user),
):
    """Compare CF users. Results are tied to the authenticated user."""
    norm = _normalized_handles(handles)
    handle_list = [h.strip() for h in norm.split(",") if h.strip()]

    if len(handle_list) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 handles")
    if len(handle_list) > 5:
        raise HTTPException(status_code=400, detail="Max 5 handles")

    db = SessionLocal()
    try:
        # Check cache (per-user)
        cached = check_cache(db, user.id, norm)
        if cached:
            return cached

        # Fetch from CF API
        users_data = []
        for handle in handle_list:
            try:
                ui = await cf_request("user.info", {"handles": handle})
                ud = ui[0] if isinstance(ui, list) else ui

                rh = await cf_request("user.rating", {"handle": handle})
                subs = await cf_request("user.status", {"handle": handle, "count": 10000})

                solved = set()
                for s in subs:
                    if s.get("verdict") == "OK" and s.get("problem"):
                        p = s["problem"]
                        solved.add((p.get("contestId"), p.get("index")))

                users_data.append({
                    "handle": ud.get("handle", handle),
                    "rating": ud.get("rating"),
                    "rank": ud.get("rank"),
                    "max_rating": ud.get("maxRating"),
                    "max_rank": ud.get("maxRank"),
                    "solved_count": len(solved),
                    "rating_history": format_rating_history(rh),
                    "tag_stats": compute_tag_stats(subs),
                })
            except HTTPException as e:
                users_data.append({
                    "handle": handle, "found": False,
                    "error": str(e.detail), "rating_history": [], "tag_stats": {},
                })

        if not any(u.get("found", True) for u in users_data):
            raise HTTPException(status_code=404, detail="No users found")

        comp_id = save_comparison(db, user.id, norm, users_data)
        return ComparisonPayload(
            users=[UserStats(**u) for u in users_data],
            cached=False, comparison_id=comp_id,
        )
    finally:
        db.close()


@app.get("/history", response_model=List[HistoryEntry])
async def get_history(
    limit: int = Query(20, ge=1, le=100),
    user: CFUser = Depends(get_current_user),
):
    """Return THIS user's last N comparisons."""
    db = SessionLocal()
    try:
        comps = (
            db.query(ComparisonModel)
            .filter(ComparisonModel.user_id == user.id)
            .order_by(ComparisonModel.created_at.desc())
            .limit(limit)
            .all()
        )
        out = []
        for c in comps:
            results = db.query(ComparisonResultModel).filter(
                ComparisonResultModel.comparison_id == c.id
            ).all()
            out.append(HistoryEntry(
                id=c.id, handles=c.handles,
                created_at=c.created_at.isoformat() if c.created_at else None,
                users=[UserStats(
                    handle=r.handle, rating=r.rating, rank=r.rank,
                    max_rating=r.max_rating, max_rank=r.max_rank,
                    solved_count=r.solved_count,
                    rating_history=r.rating_history or [],
                    tag_stats=r.tag_stats or {},
                ) for r in results],
            ))
        return out
    finally:
        db.close()


@app.get("/comparison/{comp_id}")
async def get_comparison(
    comp_id: int,
    user: CFUser = Depends(get_current_user),
):
    """Get a specific comparison — only if it belongs to this user."""
    db = SessionLocal()
    try:
        comp = db.query(ComparisonModel).filter(
            ComparisonModel.id == comp_id,
            ComparisonModel.user_id == user.id,
        ).first()
        if not comp:
            raise HTTPException(status_code=404, detail="Comparison not found")

        results = db.query(ComparisonResultModel).filter(
            ComparisonResultModel.comparison_id == comp_id
        ).all()
        insight = db.query(InsightModel).filter(
            InsightModel.comparison_id == comp_id
        ).first()

        return {
            "id": comp.id, "handles": comp.handles,
            "created_at": comp.created_at.isoformat() if comp.created_at else None,
            "users": [UserStats(
                handle=r.handle, rating=r.rating, rank=r.rank,
                max_rating=r.max_rating, max_rank=r.max_rank,
                solved_count=r.solved_count,
                rating_history=r.rating_history or [],
                tag_stats=r.tag_stats or {},
            ) for r in results],
            "insight": insight.content if insight else None,
        }
    finally:
        db.close()


@app.get("/comparison/{comp_id}/insight", response_model=InsightPayload)
async def get_or_generate_insight(
    comp_id: int,
    user: CFUser = Depends(get_current_user),
):
    """Return or generate insight for a comparison owned by this user."""
    db = SessionLocal()
    try:
        # Verify ownership
        comp = db.query(ComparisonModel).filter(
            ComparisonModel.id == comp_id,
            ComparisonModel.user_id == user.id,
        ).first()
        if not comp:
            raise HTTPException(status_code=404, detail="Comparison not found")

        existing = db.query(InsightModel).filter(
            InsightModel.comparison_id == comp_id
        ).first()
        if existing:
            return InsightPayload(comparison_id=comp_id, content=existing.content)

        results = db.query(ComparisonResultModel).filter(
            ComparisonResultModel.comparison_id == comp_id
        ).all()
        users_data = [{
            "handle": r.handle, "rating": r.rating,
            "solved_count": r.solved_count, "tag_stats": r.tag_stats or {},
        } for r in results]

        prompt = _build_prompt(users_data)
        content = await _call_llm(prompt)

        db.add(InsightModel(comparison_id=comp_id, content=content))
        db.commit()
        return InsightPayload(comparison_id=comp_id, content=content)
    finally:
        db.close()


# ─── Stats & Analytics Endpoints ──────────────────────────────────────────

# ─── 1. Rating Progress Over Time ─────────────────────────────────────────

@app.get("/stats/rating-progress/{handle}")
async def rating_progress(handle: str, user: CFUser = Depends(get_current_user)):
    """
    For a given CF handle, return all stored (created_at, rating) pairs
    from comparison_results, ordered by time.

    This shows how the user's rating evolved each time someone compared them.
    """
    db = SessionLocal()
    try:
        rows = db.execute(
            text("""
                SELECT c.created_at, cr.rating
                FROM comparison_results cr
                JOIN comparisons c ON c.id = cr.comparison_id
                WHERE LOWER(cr.handle) = LOWER(:handle)
                  AND cr.rating IS NOT NULL
                ORDER BY c.created_at ASC
            """),
            {"handle": handle},
        ).fetchall()

        return {
            "handle": handle,
            "data_points": [
                {"timestamp": r[0].isoformat() if r[0] else None, "rating": r[1]}
                for r in rows
            ],
        }
    finally:
        db.close()


# ─── 2. Most Improved Users ─────────────────────────────────────────────

@app.get("/stats/improvement")
async def most_improved(limit: int = Query(20, ge=1, le=100)):
    """
    Find CF handles with the largest rating improvement.
    Improvement = max(rating) - min(rating) across all stored comparisons.
    Only considers handles compared at least twice.
    """
    db = SessionLocal()
    try:
        rows = db.execute(
            text(f"""
                SELECT
                    cr.handle,
                    MAX(cr.rating) AS max_rating,
                    MIN(cr.rating) AS min_rating,
                    MAX(cr.rating) - MIN(cr.rating) AS improvement,
                    COUNT(*) AS comparisons
                FROM comparison_results cr
                WHERE cr.rating IS NOT NULL
                GROUP BY cr.handle
                HAVING COUNT(*) >= 2
                ORDER BY improvement DESC
                LIMIT :lim
            """),
            {"lim": limit},
        ).fetchall()

        return {
            "users": [
                {
                    "handle": r[0],
                    "max_rating": r[1],
                    "min_rating": r[2],
                    "improvement": r[3],
                    "times_compared": r[4],
                }
                for r in rows
            ]
        }
    finally:
        db.close()


# ─── 3. Head-to-Head ────────────────────────────────────────────────────

@app.get("/stats/head-to-head")
async def head_to_head(
    userA: str = Query(..., min_length=1),
    userB: str = Query(..., min_length=1),
):
    """
    For every comparison where BOTH userA and userB were compared together,
    count how many times each had a higher rating.

    Returns: wins for A, wins for B, draws, total comparisons together.
    """
    db = SessionLocal()
    try:
        rows = db.execute(
            text("""
                SELECT c.id, a.rating AS rating_a, b.rating AS rating_b
                FROM comparisons c
                JOIN comparison_results a ON a.comparison_id = c.id AND LOWER(a.handle) = LOWER(:a)
                JOIN comparison_results b ON b.comparison_id = c.id AND LOWER(b.handle) = LOWER(:b)
                WHERE a.rating IS NOT NULL AND b.rating IS NOT NULL
                ORDER BY c.created_at ASC
            """),
            {"a": userA, "b": userB},
        ).fetchall()

        wins_a = sum(1 for r in rows if r[1] > r[2])
        wins_b = sum(1 for r in rows if r[2] > r[1])
        draws = sum(1 for r in rows if r[1] == r[2])

        # Build a timeline
        timeline = []
        for i, r in enumerate(rows):
            timeline.append({
                "comparison_id": r[0],
                "rating_a": r[1],
                "rating_b": r[2],
                "winner": userA if r[1] > r[2] else (userB if r[2] > r[1] else "draw"),
            })

        return {
            "userA": userA,
            "userB": userB,
            "wins_a": wins_a,
            "wins_b": wins_b,
            "draws": draws,
            "total_comparisons": len(rows),
            "timeline": timeline,
        }
    finally:
        db.close()


# ─── 4. Leaderboard ─────────────────────────────────────────────────────

@app.get("/stats/leaderboard")
async def leaderboard(limit: int = Query(20, ge=1, le=100)):
    """
    Top CF handles by their best-ever stored rating.
    """
    db = SessionLocal()
    try:
        rows = db.execute(
            text(f"""
                SELECT
                    cr.handle,
                    MAX(cr.rating) AS best_rating,
                    MAX(cr.max_rating) AS best_ever_max,
                    COUNT(*) AS times_compared
                FROM comparison_results cr
                WHERE cr.rating IS NOT NULL
                GROUP BY cr.handle
                ORDER BY best_rating DESC
                LIMIT :lim
            """),
            {"lim": limit},
        ).fetchall()

        return {
            "leaderboard": [
                {
                    "rank": i + 1,
                    "handle": r[0],
                    "best_rating": r[1],
                    "best_max_rating": r[2],
                    "times_compared": r[3],
                }
                for i, r in enumerate(rows)
            ]
        }
    finally:
        db.close()


# ─── 5. Activity Over Time ──────────────────────────────────────────────

@app.get("/stats/activity")
async def activity(user: CFUser = Depends(get_current_user)):
    """
    Number of comparisons per day for this user.
    Returns a list of {date, count} sorted by date.
    """
    db = SessionLocal()
    try:
        rows = db.execute(
            text("""
                SELECT
                    DATE(created_at) AS day,
                    COUNT(*) AS comparison_count
                FROM comparisons
                WHERE user_id = :uid
                GROUP BY day
                ORDER BY day ASC
            """),
            {"uid": user.id},
        ).fetchall()

        return {
            "activity": [
                {"date": r[0].isoformat(), "comparisons": r[1]}
                for r in rows
            ],
            "total_comparisons": sum(r[1] for r in rows),
            "total_days": len(rows),
        }
    finally:
        db.close()


# ─── Main ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
