from phi.agent.agent import Agent
from phi.model.groq.groq import Groq
from phi.tools.googlesearch import GoogleSearch
from dotenv import load_dotenv
from fastapi import FastAPI, Body
from fastapi.middleware.cors import CORSMiddleware
from database import SessionLocal, User, Result
import datetime
import time
import hashlib
from fastapi import FastAPI, Body, HTTPException
from dotenv import load_dotenv
import os
from fastapi import FastAPI
from database import init_db
from pydantic import BaseModel

app = FastAPI()

init_db()

load_dotenv()  # يحمل المتغيرات من ملف .env
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY not found. Please add it to your .env file.")
# ===============================
# BUILD AGENT (Groq)
# ===============================
agent = Agent(
    model=Groq(
        id="llama-3.3-70b-versatile",
        max_tokens=3000,
        api_key=GROQ_API_KEY   # <-- هذا التعديل
    ),
    tools=[GoogleSearch()],
    instructions=[
        "You are a strict expert AI assistant specialized ONLY in Computer Science.",
        "Refuse non-CS questions politely.",
        "Generate a professional academic title DIFFERENT from the user's question."
    ],
    markdown=True
)


def safe_agent_run(prompt, retries=3, delay=2):
    for i in range(retries):
        try:
            return agent.run(prompt)
        except Exception as e:
            print(f"Attempt {i+1} failed: {e}")
            time.sleep(delay * (2 ** i))
    raise RuntimeError("Agent failed after multiple retries.")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
import hashlib

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()
# ===============================
# AUTH
# ===============================
class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/register")
def register(payload: dict = Body(...)):
    db = SessionLocal()
    try:
        username = payload.get("username", "").strip()
        password = payload.get("password", "").strip()

        if not username or not password:
            raise HTTPException(status_code=400, detail="Missing username or password")

        existing_user = db.query(User).filter(User.username == username).first()
        if existing_user:
            raise HTTPException(status_code=400, detail="User already exists")

        new_user = User(
            username=username,
            password=hash_password(password)
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        return {
            "username": new_user.username,
            "message": "Account created successfully ✔"
        }
    finally:
        db.close()
@app.post("/login")
def login(data: LoginRequest):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == data.username).first()

        if not user:
            raise HTTPException(status_code=400, detail="User not found")

        if user.password != hash_password(data.password):
            raise HTTPException(status_code=400, detail="Wrong password")

        return {"message": "Login success"}

    finally:
        db.close()
# ===============================
# ASK AI (Prompt الأصلي)
# ===============================
@app.post("/ask")
def ask(payload: dict = Body(...)):
    db = SessionLocal()
    question = payload.get("question")
    username = payload.get("username")

    if not question or not username:
        db.close()
        return {"detail": "Missing fields"}

    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")

    prompt = f"""
You are a Computer Science professor and academic assistant.

IMPORTANT RULE:
If the user's question is NOT related to Computer Science,
respond ONLY with the following sentence and nothing else:

"This application is specialized only in Computer Science topics. Please ask a question related to this field."

If the question IS related to Computer Science,
generate a **detailed and comprehensive educational document in Markdown**.

The user is a student seeking understanding, not just a short answer.

Use EXACTLY the following sections and order, giving **detailed explanations, examples, diagrams (if possible), and clarifications**:

## Title
- Generate a professional academic title DIFFERENT from the user's question.

## Date
- {date_str}

## Your Thoughts
- Provide a detailed interpretation of the student's problem.
- Explain why this topic is important in Computer Science.

## Direct Answer
- Provide a long, thorough explanation.
- Include examples, comparisons, step-by-step reasoning, and potential pitfalls.

## Verified Facts
- List accurate and well-known facts or concepts.
- Include references to textbooks or official documentation when possible.

## Learning Resources
- Provide **multiple reliable learning resources** using real Markdown links.
- Include tutorials, official documentation, or online courses.

## Summary
- Summarize the key ideas in a few detailed paragraphs.
- Emphasize practical understanding and connections between concepts.

## Recommendations
- Give practical advice for mastering this topic.
- Suggest exercises, projects, or further reading.

Guidelines:
- Use clear, simple, and precise language.
- Explain like a university professor teaching a student for at least 15–20 minutes of reading.
- Avoid unnecessary complexity, but go in depth.
- Include examples and clarifications wherever helpful.
- Do NOT mention being an AI.
- Do NOT add extra sections.

User Question:
\"\"\"{question}\"\"\"
"""
    response = safe_agent_run(prompt)
    content = response.content

    # استخراج العنوان
    lines = content.split("\n")
    generated_title = "Computer Science Analysis"
    capture_title = False
    for line in lines:
        if "## Title" in line:
            capture_title = True
            continue
        if capture_title and line.strip():
            generated_title = line.strip()
            break

    # حفظ النتيجة
    new_result = Result(
        username=username,
        title=generated_title,
        content=content
    )
    db.add(new_result)
    db.commit()
    db.refresh(new_result)
    db.close()

    return {
        "id": new_result.id,
        "title": generated_title,
        "date": date_str,
        "answer": content
    }

# ===============================
# GET ALL RESULTS
# ===============================
@app.get("/results/{username}")
def get_results(username: str):
    db = SessionLocal()
    results = db.query(Result).filter(Result.username == username).order_by(Result.created_at.desc()).all()
    db.close()
    return [{"id": r.id, "title": r.title, "time": r.created_at} for r in results]

# ===============================
# GET SINGLE RESULT
# ===============================
@app.get("/result/{result_id}")
def get_result(result_id: int):
    db = SessionLocal()
    result = db.query(Result).filter(Result.id == result_id).first()
    db.close()
    if not result:
        return {"detail": "Not found"}
    return {"id": result.id, "title": result.title, "content": result.content, "time": result.created_at}

# ===============================
# DELETE RESULT
# ===============================
@app.delete("/result/{result_id}")
def delete_result(result_id: int):
    db = SessionLocal()
    result = db.query(Result).filter(Result.id == result_id).first()
    if not result:
        db.close()
        return {"detail": "Not found"}
    db.delete(result)
    db.commit()
    db.close()
    return {"status": "deleted"}

# ===============================
# RUN
# ===============================
port = int(os.environ.get("PORT", 8000))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=port)