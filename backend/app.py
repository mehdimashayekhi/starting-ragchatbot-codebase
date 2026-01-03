import warnings
warnings.filterwarnings("ignore", message="resource_tracker: There appear to be.*")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel
from typing import List, Optional
import os

from config import config
from rag_system import RAGSystem
from models import SourceCitation, ChatHistoryItem

# Initialize FastAPI app
app = FastAPI(title="Course Materials RAG System", root_path="")

# Add trusted host middleware for proxy
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"]
)

# Enable CORS with proper settings for proxy
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Initialize RAG system
rag_system = RAGSystem(config)

# Pydantic models for request/response
class QueryRequest(BaseModel):
    """Request model for course queries"""
    query: str
    session_id: Optional[str] = None

class QueryResponse(BaseModel):
    """Response model for course queries"""
    answer: str
    sources: List[SourceCitation]
    session_id: str

class CourseStats(BaseModel):
    """Response model for course statistics"""
    total_courses: int
    course_titles: List[str]

# API Endpoints

@app.post("/api/query", response_model=QueryResponse)
async def query_documents(request: QueryRequest):
    """Process a query and return response with sources"""
    try:
        # Create session if not provided
        session_id = request.session_id
        if not session_id:
            session_id = rag_system.session_manager.create_session()
        
        # Process query using RAG system
        answer, sources = rag_system.query(request.query, session_id)
        
        return QueryResponse(
            answer=answer,
            sources=sources,
            session_id=session_id
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/courses", response_model=CourseStats)
async def get_course_stats():
    """Get course analytics and statistics"""
    try:
        analytics = rag_system.get_course_analytics()
        return CourseStats(
            total_courses=analytics["total_courses"],
            course_titles=analytics["course_titles"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/chat-history", response_model=List[ChatHistoryItem])
async def get_chat_history():
    """Get list of recent chats with titles extracted from first user message"""
    try:
        chats = []
        all_sessions = rag_system.session_manager.sessions

        # Sort sessions by ID number (most recent first)
        sorted_session_ids = sorted(
            all_sessions.keys(),
            key=lambda x: int(x.split('_')[1]),
            reverse=True
        )

        # Limit to 10 most recent chats
        for session_id in sorted_session_ids[:10]:
            messages = all_sessions[session_id]

            # Skip empty sessions
            if not messages:
                continue

            # Find first user message for title
            first_user_msg = None
            for msg in messages:
                if msg.role == "user":
                    first_user_msg = msg.content
                    break

            if first_user_msg:
                # Truncate title to 50 characters
                title = first_user_msg[:50]
                if len(first_user_msg) > 50:
                    title += "..."

                chats.append(ChatHistoryItem(
                    session_id=session_id,
                    title=title,
                    message_count=len(messages)
                ))

        return chats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/chat/{session_id}")
async def get_chat_conversation(session_id: str):
    """Get full conversation history for a session (read-only mode)"""
    try:
        if session_id not in rag_system.session_manager.sessions:
            raise HTTPException(status_code=404, detail="Chat not found")

        messages = rag_system.session_manager.sessions.get(session_id, [])

        return {
            "session_id": session_id,
            "messages": [
                {
                    "role": msg.role,
                    "content": msg.content
                }
                for msg in messages
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.on_event("startup")
async def startup_event():
    """Load initial documents on startup"""
    docs_path = "../docs"
    if os.path.exists(docs_path):
        print("Loading initial documents...")
        try:
            courses, chunks = rag_system.add_course_folder(docs_path, clear_existing=False)
            print(f"Loaded {courses} courses with {chunks} chunks")
        except Exception as e:
            print(f"Error loading documents: {e}")

# Custom static file handler with no-cache headers for development
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
from pathlib import Path


class DevStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if isinstance(response, FileResponse):
            # Add no-cache headers for development
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response
    
    
# Serve static files for the frontend
app.mount("/", StaticFiles(directory="../frontend", html=True), name="static")