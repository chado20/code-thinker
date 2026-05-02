from phi.agent.agent import Agent
from phi.model.groq.groq import Groq
from phi.tools.googlesearch import GoogleSearch
from dotenv import load_dotenv
from fastapi import FastAPI, Body, HTTPException, Request, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from database import SessionLocal, User, Result, init_db
import datetime
import time
import hashlib
import os

# --- إعداد تطبيق FastAPI ---
app = FastAPI()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- إعداد نظام القوالب (Jinja2) لعرض صفحات HTML من مجلد frontend ---
templates = Jinja2Templates(
    directory=os.path.join(BASE_DIR, "..", "frontend")
)

# --- مسار صفحة تسجيل الدخول (الواجهة الافتراضية) ---
@app.get("/", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

# --- مسار الصفحة الرئيسية للتطبيق بعد الدخول ---
@app.get("/home", response_class=HTMLResponse)
def home_page(request: Request, username: str = ""):
    return templates.TemplateResponse("app.html", {
        "request": request,
        "username": username
    })

# --- تهيئة قاعدة البيانات عند تشغيل السيرفر ---
init_db()

# --- تحميل مفتاح API الخاص بـ Groq من ملف البيئة .env ---
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY not found. Please add it to your .env file.")

# ===============================
# إعداد العميل الذكي (Groq Agent)
# ===============================
agent = Agent(
    model=Groq(
        id="llama-3.3-70b-versatile",
        max_tokens=3000,
        api_key=GROQ_API_KEY
    ),
    tools=[GoogleSearch()], # أداة البحث في جوجل لجلب معلومات حديثة
    instructions=[
        "You are a strict expert AI assistant specialized ONLY in Computer Science.",
        "Refuse non-CS questions politely.",
        "Generate a professional academic title DIFFERENT from the user's question."
    ],
    markdown=True
)

# --- وظيفة لتشغيل العميل الذكي مع ميزة "إعادة المحاولة" في حال حدوث خطأ في الشبكة ---
def safe_agent_run(prompt, retries=3, delay=2):
    for i in range(retries):
        try:
            return agent.run(prompt)
        except Exception as e:
            print(f"Attempt {i+1} failed: {e}")
            time.sleep(delay * (2 ** i)) # زيادة وقت الانتظار تدريجياً (Exponential Backoff)
    raise RuntimeError("Agent failed after multiple retries.")

# --- إعدادات CORS للسماح بطلبات من مصادر مختلفة (مهمة لعمل الـ API) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- وظيفة لتشفير كلمة المرور لحماية بيانات المستخدمين ---
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

# ===============================
# نظام إدارة المستخدمين (Auth)
# ===============================

class LoginRequest(BaseModel):
    username: str
    password: str

# --- مسار إنشاء حساب جديد ---
@app.post("/register")
def register(username: str = Form(...), password: str = Form(...)):
    db = SessionLocal() # فتح اتصال بقاعدة البيانات
    try:
        username = username.strip()
        password = password.strip()

        if not username or not password:
            raise HTTPException(status_code=400, detail="Missing username or password")

        # التأكد من أن اسم المستخدم غير مكرر
        existing_user = db.query(User).filter(User.username == username).first()
        if existing_user:
            raise HTTPException(status_code=400, detail="User already exists")

        # حفظ المستخدم الجديد بكلمة مرور مشفرة
        new_user = User(
            username=username,
            password=hash_password(password)
        )
        db.add(new_user)
        db.commit()

        return {
            "username": username,
            "message": "Account created successfully ✔ Now login"
        }
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
    finally:
        db.close() # إغلاق الاتصال دائماً

# --- مسار تسجيل الدخول والتحقق من الهوية ---
@app.post("/login")
def login(username: str = Form(...), password: str = Form(...)):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()

        if not user:
             raise HTTPException(status_code=400, detail="User not found")
        if user.password != hash_password(password):
            raise HTTPException(status_code=400, detail="Wrong password")
        
        # عند النجاح، يتم التوجه للصفحة الرئيسية مع اسم المستخدم
        return RedirectResponse(url=f"/home?username={username}", status_code=303)

    finally:
        db.close()

# ===============================
# نظام سؤال الذكاء الاصطناعي (AI Interaction)
# ===============================

@app.post("/ask")
def ask(username: str = Form(...), question: str = Form(...)):
    db = SessionLocal()
    try:
        if not question or not username:
            return {"detail": "Missing fields"}

        now = datetime.datetime.now()
        date_str = now.strftime("%Y-%m-%d")

        # --- البرومبت (Prompt) الذي يحدد شخصية الأستاذ الجامعي وطريقة الإجابة ---
        prompt = f"""
You are a Computer Science professor and academic assistant.
IMPORTANT RULE:
If the user's question is NOT related to Computer Science,
respond ONLY with the following sentence:
"This application is specialized only in Computer Science topics. Please ask a question related to this field."

If the question IS related to Computer Science, 
generate a **detailed and comprehensive educational document in Markdown**.
... (بقية تعليمات التنسيق الأكاديمي) ...
User Question:
\"\"\"{question}\"\"\"
"""
        # تشغيل العميل الذكي لجلب الإجابة
        response = safe_agent_run(prompt)
        content = response.content

        # --- استخراج العنوان المولد من النص الناتج ---
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

        # --- حفظ السؤال والإجابة في قاعدة البيانات للرجوع إليها لاحقاً ---
        new_result = Result(
            username=username,
            title=generated_title,
            content=content
        )
        db.add(new_result)
        db.commit()
        db.refresh(new_result)

        return {
            "id": new_result.id,
            "title": generated_title,
            "date": date_str,
            "answer": content
        }

    except Exception as e:
        print(f"Error in ask: {e}")
        raise HTTPException(status_code=500, detail="Agent Error")
    
    finally:
        db.close()

# ===============================
# إدارة الأرشيف (تاريخ العمليات)
# ===============================

# جلب كافة النتائج السابقة لمستخدم معين
@app.get("/results/{username}")
def get_results(username: str):
    db = SessionLocal()
    results = db.query(Result).filter(Result.username == username).order_by(Result.created_at.desc()).all()
    db.close()
    return [{"id": r.id, "title": r.title, "time": r.created_at} for r in results]

# جلب تفاصيل نتيجة واحدة محددة
@app.get("/result/{result_id}")
def get_result(result_id: int):
    db = SessionLocal()
    result = db.query(Result).filter(Result.id == result_id).first()
    db.close()
    if not result:
        return {"detail": "Not found"}
    return {"id": result.id, "title": result.title, "content": result.content, "time": result.created_at}

# حذف نتيجة معينة من الأرشيف
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

# --- نقطة انطلاق التطبيق ---
if __name__ == "__main__":
    import uvicorn
    # تشغيل السيرفر على البورت المحدد
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
