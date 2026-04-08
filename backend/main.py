"""
CF Compare - Backend API
Main FastAPI application with routes for comparing Codeforces users.
"""

import os
import hashlib
import hmac
import json
import time
import httpx
from typing import List
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, Text, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ─── Database Setup ───────────────────────────────────────────────────────

# Database connection using service name from docker-compose
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://cfuser:cfpassword@db:5432/cfcompare"
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# Comparison model for database
class ComparisonModel(Base):
    """Database model to store comparison results."""
    __tablename__ = "comparisons"

    id = Column(Integer, primary_key=True, index=True)
    handles = Column(Text, nullable=False)  # Comma-separated handles
    result = Column(Text, nullable=False)   # JSON string of results
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# Create tables
Base.metadata.create_all(bind=engine)


# ─── FastAPI App ──────────────────────────────────────────────────────────

app = FastAPI(title="CF Compare API", version="1.0.0")

# CORS - allow frontend to access backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Codeforces API Integration ───────────────────────────────────────────

# API credentials from .env file (used for authenticated requests)
API_KEY = os.getenv("API_KEY", "")
API_SECRET = os.getenv("API_SECRET", "")

CODEFORCES_API_URL = "https://codeforces.com/api"


def generate_api_signature(method: str, params: dict) -> str:
    """
    Generate API signature for Codeforces authenticated requests.
    Required for some API methods.
    """
    if not API_KEY or not API_SECRET:
        return ""

    # Sort parameters and build signature string
    param_str = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
    sig_string = f"{method}/{param_str}#{API_SECRET}"

    # Generate SHA512 hash
    return hashlib.sha512(sig_string.encode()).hexdigest()


async def codeforces_request(method: str, params: dict) -> dict:
    """
    Make a request to Codeforces API with optional authentication.
    Public endpoints (user.info, user.rating, user.status) don't require API key.
    """
    # Note: Codeforces public API methods don't need authentication.
    # We only use API_KEY/SECRET for private methods if needed in the future.
    # For now, skip authentication for public endpoints to avoid signature errors.

    url = f"{CODEFORCES_API_URL}/{method}"

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, params=params)

        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Codeforces API error: {response.text}"
            )

        data = response.json()

        if data.get("status") != "OK":
            raise HTTPException(
                status_code=400,
                detail=f"Codeforces API returned error: {data.get('comment', 'Unknown error')}"
            )

        return data["result"]


# ─── Pydantic Models ──────────────────────────────────────────────────────

class UserComparison(BaseModel):
    """Structure for a single user's comparison data."""
    handle: str
    rating: int | None = None
    rank: str | None = None
    maxRating: int | None = None
    maxRank: str | None = None
    solved_count: int = 0
    found: bool = True
    error: str | None = None


class ComparisonResponse(BaseModel):
    """Full comparison response."""
    users: List[UserComparison]
    saved_id: int | None = None


# ─── API Routes ───────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/compare", response_model=ComparisonResponse)
async def compare_users(handles: str = Query(..., min_length=1)):
    """
    Compare multiple Codeforces users.

    - **handles**: Comma-separated list of Codeforces handles (e.g., 'tourist,petr')
    """
    # Parse handles
    handle_list = [h.strip() for h in handles.split(",") if h.strip()]

    if len(handle_list) < 2:
        raise HTTPException(
            status_code=400,
            detail="Please provide at least 2 handles separated by commas"
        )

    if len(handle_list) > 5:
        raise HTTPException(
            status_code=400,
            detail="Maximum 5 handles allowed"
        )

    results = []

    # Fetch data for each user
    for handle in handle_list:
        try:
            # Fetch user info (rating, rank, etc.)
            user_info = await codeforces_request(
                "user.info",
                {"handles": handle}
            )
            user_data = user_info[0] if isinstance(user_info, list) else user_info

            # Fetch user rating history
            rating_history = await codeforces_request(
                "user.rating",
                {"handle": handle}
            )

            # Fetch user submissions to count solved problems
            submissions = await codeforces_request(
                "user.status",
                {"handle": handle, "count": 10000}  # Get max submissions
            )

            # Count unique solved problems
            solved_problems = set()
            for sub in submissions:
                if sub.get("verdict") == "OK" and sub.get("problem"):
                    problem = sub["problem"]
                    # Unique problem identified by contestId + index
                    problem_id = (
                        problem.get("contestId", ""),
                        problem.get("index", "")
                    )
                    solved_problems.add(problem_id)

            # Build user comparison data
            user_comparison = UserComparison(
                handle=handle,
                rating=user_data.get("rating"),
                rank=user_data.get("rank"),
                maxRating=user_data.get("maxRating"),
                maxRank=user_data.get("maxRank"),
                solved_count=len(solved_problems)
            )
            results.append(user_comparison)

        except HTTPException as e:
            # User not found — add placeholder instead of failing whole request
            if e.status_code == 400:
                results.append(UserComparison(
                    handle=handle,
                    found=False,
                    error=f"User not found"
                ))
            else:
                results.append(UserComparison(
                    handle=handle,
                    found=False,
                    error=str(e.detail)
                ))
        except Exception as e:
            results.append(UserComparison(
                handle=handle,
                found=False,
                error=str(e)
            ))

    # Save to database
    db = SessionLocal()
    saved_id = None

    # If no users were found at all, return error
    found_users = [u for u in results if u.found]
    if not found_users:
        db.close()
        raise HTTPException(
            status_code=404,
            detail="None of the provided handles were found on Codeforces"
        )

    try:
        # Convert results to JSON
        result_json = json.dumps([u.dict() for u in results])

        comparison = ComparisonModel(
            handles=",".join(handle_list),
            result=result_json
        )
        db.add(comparison)
        db.commit()
        db.refresh(comparison)
        saved_id = comparison.id
    except Exception as e:
        db.rollback()
        print(f"Warning: Could not save comparison to database: {e}")
    finally:
        db.close()

    return ComparisonResponse(users=results, saved_id=saved_id)


@app.get("/comparisons")
async def get_saved_comparisons(limit: int = 10):
    """Get recent saved comparisons from database."""
    db = SessionLocal()
    try:
        comparisons = (
            db.query(ComparisonModel)
            .order_by(ComparisonModel.created_at.desc())
            .limit(limit)
            .all()
        )

        return [
            {
                "id": c.id,
                "handles": c.handles,
                "result": json.loads(c.result),
                "created_at": c.created_at.isoformat() if c.created_at else None
            }
            for c in comparisons
        ]
    finally:
        db.close()


@app.get("/comparisons/{comparison_id}")
async def get_comparison(comparison_id: int):
    """Get a specific saved comparison by ID."""
    db = SessionLocal()
    try:
        comparison = (
            db.query(ComparisonModel)
            .filter(ComparisonModel.id == comparison_id)
            .first()
        )

        if not comparison:
            raise HTTPException(status_code=404, detail="Comparison not found")

        return {
            "id": comparison.id,
            "handles": comparison.handles,
            "result": json.loads(comparison.result),
            "created_at": comparison.created_at.isoformat() if comparison.created_at else None
        }
    finally:
        db.close()


# ─── Main Entry Point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
