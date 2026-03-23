from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from dotenv import load_dotenv
import json
import os

# Load variables from the .env file
load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"], 
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pull keys securely from the environment
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Helper to load JSON
def load_json(filename):
    with open(f"data/{filename}", "r") as file:
        return json.load(file)

@app.get("/api/dashboard/{user_id}")
async def get_dashboard_data(user_id: str, email: str):
    """Fetches history dynamically based on email, and saved schedules based on user_id."""
    
    # Get dynamic mock history from JSON using the email
    history_data = load_json("student_history.json")
    
    # If the email isn't in our JSON, give them a blank slate instead of crashing
    default_history = {"completed_courses": [], "gpa": 0.0}
    student_history = history_data.get(email, default_history)
    
    # Get saved upcoming schedule from Supabase (this uses the real user_id)
    try:
        response = supabase.table("saved_schedules").select("*").eq("user_id", user_id).execute()
        upcoming_schedules = response.data
    except Exception as e:
        upcoming_schedules = []

    return {
        "history": student_history,
        "upcoming": upcoming_schedules
    }

# run with: uvicorn main:app --reload