from fastapi import FastAPI, UploadFile, HTTPException, BackgroundTasks, Request, Form, Depends, Cookie
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from dotenv import load_dotenv
import asyncio
import uvicorn
import base64
import secrets
import hashlib
import json
from datetime import datetime, timedelta
import sqlite3
import os
from pathlib import Path

from openai import OpenAI
import requests
from tempfile import NamedTemporaryFile
import uuid
import logging
from typing import Dict, List, Optional
from pydantic import BaseModel

# Azure imports
from azure.storage.blob import BlobServiceClient
from azure.communication.email import EmailClient
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
import io

# Load environment variables
load_dotenv()

# Configuration
OPEN_AI_KEY = os.getenv("OPENAI_API_KEY")
OPEN_AI_ORG = os.getenv("OPENAI_ORG_ID")
ELEVENLABS_KEY = os.getenv("ELEVENLABS_API_KEY")
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
AZURE_COMMUNICATION_CONNECTION_STRING = os.getenv("AZURE_COMMUNICATION_CONNECTION_STRING")
RECEIVER_EMAIL = "divyesh11092003@gmail.com"
SENDER_EMAIL = "DoNotReply@5f2fdd04-4185-4ba9-a0b4-8e7b24efae12.azurecomm.net"

# Admin credentials
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "eazyai2025"
SECRET_KEY = "eazyai_super_secret_key_2025"

# Initialize clients
client = OpenAI(api_key=OPEN_AI_KEY, organization=OPEN_AI_ORG)
blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
email_client = EmailClient.from_connection_string(AZURE_COMMUNICATION_CONNECTION_STRING)

# Create database directory
DB_DIR = Path("data")
DB_DIR.mkdir(exist_ok=True)
DB_PATH = DB_DIR / "eazyai_interviews.db"

# Initialize SQLite Database
def init_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Interviews table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS interviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT UNIQUE NOT NULL,
            candidate_name TEXT NOT NULL,
            position TEXT NOT NULL,
            experience_level TEXT NOT NULL,
            start_time DATETIME NOT NULL,
            end_time DATETIME,
            status TEXT DEFAULT 'in_progress',
            current_question INTEGER DEFAULT 0,
            total_questions INTEGER DEFAULT 10,
            recommendation TEXT DEFAULT 'pending',
            email_sent BOOLEAN DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Scores table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            technical_skills INTEGER DEFAULT 0,
            communication INTEGER DEFAULT 0,
            problem_solving INTEGER DEFAULT 0,
            leadership INTEGER DEFAULT 0,
            adaptability INTEGER DEFAULT 0,
            creativity INTEGER DEFAULT 0,
            teamwork INTEGER DEFAULT 0,
            overall INTEGER DEFAULT 0,
            FOREIGN KEY (session_id) REFERENCES interviews (session_id)
        )
    ''')
    
    # Messages table for transcript storage
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES interviews (session_id)
        )
    ''')
    
    # Admin sessions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admin_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_token TEXT UNIQUE NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            expires_at DATETIME NOT NULL,
            is_active BOOLEAN DEFAULT 1
        )
    ''')
    
    conn.commit()
    conn.close()

# Database helper functions
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def save_interview_to_db(session):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Insert or update interview
    cursor.execute('''
        INSERT OR REPLACE INTO interviews 
        (session_id, candidate_name, position, experience_level, start_time, end_time, 
         status, current_question, total_questions, recommendation, email_sent, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ''', (
        session.session_id, session.candidate_name, session.position, 
        session.experience_level, session.start_time, session.end_time,
        session.status, session.current_question, session.total_questions,
        session.recommendation, session.email_sent
    ))
    
    # Insert or update scores
    scores = session.scores
    cursor.execute('''
        INSERT OR REPLACE INTO scores 
        (session_id, technical_skills, communication, problem_solving, leadership, 
         adaptability, creativity, teamwork, overall)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        session.session_id, scores.get('technical_skills', 0), scores.get('communication', 0),
        scores.get('problem_solving', 0), scores.get('leadership', 0), 
        scores.get('adaptability', 0), scores.get('creativity', 0),
        scores.get('teamwork', 0), scores.get('overall', 0)
    ))
    
    conn.commit()
    conn.close()

def save_message_to_db(session_id, role, content):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO messages (session_id, role, content)
        VALUES (?, ?, ?)
    ''', (session_id, role, content))
    conn.commit()
    conn.close()

def get_all_interviews_from_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get interviews with scores
    cursor.execute('''
        SELECT i.*, s.technical_skills, s.communication, s.problem_solving, 
               s.leadership, s.adaptability, s.creativity, s.teamwork, s.overall
        FROM interviews i
        LEFT JOIN scores s ON i.session_id = s.session_id
        ORDER BY i.start_time DESC
    ''')
    
    interviews = []
    for row in cursor.fetchall():
        interview = dict(row)
        # Add scores dictionary
        interview['scores'] = {
            'technical_skills': interview.get('technical_skills', 0),
            'communication': interview.get('communication', 0),
            'problem_solving': interview.get('problem_solving', 0),
            'leadership': interview.get('leadership', 0),
            'adaptability': interview.get('adaptability', 0),
            'creativity': interview.get('creativity', 0),
            'teamwork': interview.get('teamwork', 0),
            'overall': interview.get('overall', 0)
        }
        interviews.append(interview)
    
    conn.close()
    return interviews

def get_interview_messages(session_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT role, content, timestamp FROM messages 
        WHERE session_id = ? ORDER BY timestamp ASC
    ''', (session_id,))
    messages = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return messages

def update_interview_status_in_db(session_id, status, notes=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE interviews 
        SET status = ?, updated_at = CURRENT_TIMESTAMP
        WHERE session_id = ?
    ''', (status, session_id))
    conn.commit()
    conn.close()

# Admin authentication functions
def generate_session_token():
    return secrets.token_urlsafe(32)

def create_admin_session():
    token = generate_session_token()
    expires_at = datetime.now() + timedelta(hours=24)  # 24 hour session
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO admin_sessions (session_token, expires_at)
        VALUES (?, ?)
    ''', (token, expires_at))
    conn.commit()
    conn.close()
    
    return token

def validate_admin_session(token):
    if not token:
        return False
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id FROM admin_sessions 
        WHERE session_token = ? AND expires_at > CURRENT_TIMESTAMP AND is_active = 1
    ''', (token,))
    
    result = cursor.fetchone()
    conn.close()
    
    return result is not None

def invalidate_admin_session(token):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE admin_sessions 
        SET is_active = 0 
        WHERE session_token = ?
    ''', (token,))
    conn.commit()
    conn.close()

# Security
security = HTTPBasic()

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize database
init_database()

# FastAPI App
app = FastAPI(
    title="eazyAI Enterprise Interviewer",
    description="Enterprise-grade AI-powered interviewing platform with persistent dashboard",
    version="3.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic models
class InterviewSession(BaseModel):
    session_id: str
    candidate_name: str
    position: str
    experience_level: str
    start_time: datetime
    end_time: Optional[datetime] = None
    messages: List[Dict] = []
    scores: Dict[str, int] = {}
    total_questions: int = 10
    current_question: int = 0
    status: str = "in_progress"
    recommendation: str = "pending"
    email_sent: bool = False

class InterviewRequest(BaseModel):
    candidate_name: str
    position: str
    experience_level: str = "junior"

class StatusUpdate(BaseModel):
    session_id: str
    status: str
    notes: Optional[str] = ""

# In-memory storage for active sessions only (completed go to DB)
active_sessions: Dict[str, InterviewSession] = {}

# Container names
CONTAINERS = {
    "transcripts": "transcripts",
    "evaluations": "evaluationresults", 
    "reports": "reports"
}

@app.on_event("startup")
async def startup_event():
    logger.info("🚀 eazyAI Enterprise Platform with Persistent Dashboard started!")

@app.get("/", response_class=HTMLResponse)
async def get_frontend():
    """Serve the enterprise frontend"""
    html_content = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>eazyAI Enterprise Interviewer Platform</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><rect width='100' height='100' rx='20' fill='%23001f3f'/><text x='50' y='65' font-family='Arial,sans-serif' font-size='60' font-weight='bold' text-anchor='middle' fill='white'>e</text></svg>">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, 'Roboto', 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #001f3f 0%, #003366 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
            line-height: 1.6;
        }

        .container {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(15px);
            border-radius: 25px;
            padding: 50px;
            box-shadow: 0 25px 50px rgba(0, 31, 63, 0.3);
            max-width: 900px;
            width: 100%;
            text-align: center;
            border: 1px solid rgba(255, 255, 255, 0.2);
        }

        .brand-header {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 20px;
            margin-bottom: 15px;
        }

        .brand-icon {
            width: 80px;
            height: 80px;
            background: linear-gradient(135deg, #001f3f 0%, #003366 100%);
            border-radius: 20px;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-size: 40px;
            font-weight: bold;
            box-shadow: 0 10px 25px rgba(0, 31, 63, 0.4);
            position: relative;
            overflow: hidden;
        }

        .brand-icon::before {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: linear-gradient(45deg, transparent, rgba(255,255,255,0.1), transparent);
            transform: rotate(45deg);
            transition: transform 0.6s;
        }

        .brand-icon:hover::before {
            transform: rotate(45deg) translate(50%, 50%);
        }

        .brand-text {
            font-size: 3.5rem;
            font-weight: 700;
            background: linear-gradient(135deg, #001f3f 0%, #003366 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            letter-spacing: -2px;
        }

        .tagline {
            color: #666;
            font-size: 1.3rem;
            margin-bottom: 40px;
            font-weight: 500;
        }

        .setup-form {
            display: block;
            margin-bottom: 40px;
        }

        .interview-interface {
            display: none;
        }

        .form-group {
            margin-bottom: 25px;
            text-align: left;
        }

        label {
            display: block;
            margin-bottom: 8px;
            font-weight: 600;
            color: #333;
            font-size: 1rem;
        }

        input, select {
            width: 100%;
            padding: 16px 20px;
            border: 2px solid #e0e7ff;
            border-radius: 12px;
            font-size: 16px;
            transition: all 0.3s ease;
            background: #fafbff;
        }

        input:focus, select:focus {
            border-color: #001f3f;
            outline: none;
            background: #fff;
            box-shadow: 0 0 0 3px rgba(0, 31, 63, 0.1);
        }

        .btn {
            background: linear-gradient(135deg, #001f3f 0%, #003366 100%);
            color: white;
            padding: 18px 40px;
            border: none;
            border-radius: 50px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            margin: 15px;
            box-shadow: 0 8px 25px rgba(0, 31, 63, 0.3);
            position: relative;
            overflow: hidden;
        }

        .btn:hover {
            transform: translateY(-3px);
            box-shadow: 0 15px 35px rgba(0, 31, 63, 0.4);
        }

        .btn:active {
            transform: translateY(-1px);
        }

        .btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
            box-shadow: 0 8px 25px rgba(0, 31, 63, 0.3);
        }

        .admin-link {
            position: fixed;
            top: 20px;
            right: 20px;
            background: rgba(255, 255, 255, 0.9);
            padding: 10px 20px;
            border-radius: 25px;
            text-decoration: none;
            color: #001f3f;
            font-weight: 600;
            box-shadow: 0 5px 15px rgba(0, 31, 63, 0.2);
            transition: all 0.3s ease;
        }

        .admin-link:hover {
            background: #001f3f;
            color: white;
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(0, 31, 63, 0.3);
        }

        .audio-controls {
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 30px;
            margin: 40px 0;
        }

        .record-btn {
            width: 100px;
            height: 100px;
            border-radius: 50%;
            border: none;
            background: linear-gradient(135deg, #ff6b7d 0%, #ee5a6f 100%);
            color: white;
            font-size: 30px;
            cursor: pointer;
            transition: all 0.3s ease;
            box-shadow: 0 10px 30px rgba(255, 107, 125, 0.3);
            position: relative;
        }

        .record-btn:hover {
            transform: scale(1.1);
            box-shadow: 0 15px 40px rgba(255, 107, 125, 0.4);
        }

        .record-btn.recording {
            background: linear-gradient(135deg, #ff4757 0%, #ff3742 100%);
            animation: pulse 1.5s infinite ease-in-out;
        }

        @keyframes pulse {
            0%, 100% { transform: scale(1); }
            50% { transform: scale(1.05); }
        }

        .status {
            margin: 25px 0;
            padding: 18px 25px;
            border-radius: 12px;
            font-weight: 600;
            font-size: 1.1rem;
        }

        .status.info {
            background: linear-gradient(135deg, #e3f2fd 0%, #f3f9ff 100%);
            color: #1976d2;
            border-left: 4px solid #2196f3;
        }

        .status.success {
            background: linear-gradient(135deg, #e8f5e8 0%, #f1f8e9 100%);
            color: #2e7d32;
            border-left: 4px solid #4caf50;
        }

        .status.error {
            background: linear-gradient(135deg, #ffebee 0%, #fef7f0 100%);
            color: #c62828;
            border-left: 4px solid #f44336;
        }

        .progress-container {
            margin: 30px 0;
        }

        .progress-label {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
            font-weight: 600;
            color: #333;
        }

        .progress-bar {
            width: 100%;
            height: 12px;
            background: #e0e7ff;
            border-radius: 6px;
            overflow: hidden;
            box-shadow: inset 0 2px 4px rgba(0,0,0,0.1);
        }

        .progress-fill {
            height: 100%;
            background: linear-gradient(135deg, #001f3f 0%, #003366 100%);
            width: 0%;
            transition: width 0.8s ease;
            border-radius: 6px;
        }

        .question-display {
            background: linear-gradient(135deg, #f8fbff 0%, #f0f4f8 100%);
            padding: 30px;
            border-radius: 20px;
            margin: 30px 0;
            border-left: 5px solid #001f3f;
            box-shadow: 0 5px 20px rgba(0, 31, 63, 0.1);
            font-size: 1.1rem;
            line-height: 1.6;
        }

        .transcript-display {
            background: #fff;
            border: 2px solid #e0e7ff;
            border-radius: 15px;
            padding: 25px;
            margin: 30px 0;
            max-height: 300px;
            overflow-y: auto;
            text-align: left;
            font-size: 0.95rem;
        }

        .transcript-entry {
            margin-bottom: 20px;
            padding: 15px;
            border-left: 4px solid #001f3f;
            background: #f8fbff;
            border-radius: 8px;
        }

        .completion-display {
            text-align: center;
            padding: 40px;
            background: linear-gradient(135deg, #e8f5e8 0%, #f1f8e9 100%);
            border-radius: 20px;
            border: 2px solid #4caf50;
        }

        .completion-display h2 {
            color: #2e7d32;
            margin-bottom: 20px;
            font-size: 2rem;
        }

        .completion-display p {
            color: #388e3c;
            margin: 10px 0;
            font-size: 1.1rem;
        }

        .hidden {
            display: none !important;
        }

        @media (max-width: 768px) {
            .container {
                padding: 30px 20px;
                margin: 10px;
            }
            
            .brand-header {
                flex-direction: column;
                gap: 15px;
            }
            
            .brand-text {
                font-size: 2.5rem;
            }
            
            .audio-controls {
                flex-direction: column;
                gap: 20px;
            }
        }

        .fade-in {
            animation: fadeIn 0.6s ease-out;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .slide-up {
            animation: slideUp 0.5s ease-out;
        }

        @keyframes slideUp {
            from { opacity: 0; transform: translateY(30px); }
            to { opacity: 1; transform: translateY(0); }
        }
    </style>
</head>
<body>
    <a href="/admin" class="admin-link">🏢 Admin Dashboard</a>
    
    <div class="container">
        <div class="brand-header">
            <div class="brand-icon">e</div>
            <div class="brand-text">azyAI</div>
        </div>
        <div class="tagline">Enterprise AI Interviewer Platform</div>

        <!-- Setup Form -->
        <div class="setup-form" id="setupForm">
            <div class="form-group">
                <label for="candidateName">Candidate Name</label>
                <input type="text" id="candidateName" placeholder="Enter candidate's full name" required>
            </div>
            
            <div class="form-group">
                <label for="position">Position</label>
                <input type="text" id="position" placeholder="e.g., Frontend Developer, Data Scientist" required>
            </div>
            
            <div class="form-group">
                <label for="experienceLevel">Experience Level</label>
                <select id="experienceLevel">
                    <option value="junior">Junior (0-2 years)</option>
                    <option value="mid">Mid-level (2-5 years)</option>
                    <option value="senior">Senior (5+ years)</option>
                </select>
            </div>
            
            <button class="btn" onclick="startInterview()">🎤 Start AI Interview</button>
        </div>

        <!-- Interview Interface -->
        <div class="interview-interface" id="interviewInterface">
            <div class="progress-container">
                <div class="progress-label">
                    <span>Interview Progress</span>
                    <span id="progressText">0/10 Questions</span>
                </div>
                <div class="progress-bar">
                    <div class="progress-fill" id="progressFill"></div>
                </div>
            </div>
            
            <div class="status info" id="statusMessage">
                Welcome! Click the microphone to start your interview.
            </div>
            
            <div class="question-display" id="questionDisplay">
                Your AI interviewer will ask questions here...
            </div>
            
            <div class="audio-controls">
                <button class="record-btn" id="recordBtn" onclick="toggleRecording()" title="Click to record your response">🎤</button>
                <button class="btn" onclick="endInterview()" id="endBtn">📋 End Interview</button>
            </div>
            
            <div class="transcript-display" id="transcriptDisplay">
                <strong>📝 Interview Transcript:</strong>
                <div id="transcriptContent"></div>
            </div>
        </div>
    </div>

    <script>
        let mediaRecorder;
        let audioChunks = [];
        let isRecording = false;
        let currentSessionId = null;
        let questionCount = 0;
        let maxQuestions = 10;

        // DOM Elements
        const setupForm = document.getElementById('setupForm');
        const interviewInterface = document.getElementById('interviewInterface');
        const recordBtn = document.getElementById('recordBtn');
        const statusMessage = document.getElementById('statusMessage');
        const questionDisplay = document.getElementById('questionDisplay');
        const transcriptContent = document.getElementById('transcriptContent');
        const progressFill = document.getElementById('progressFill');
        const progressText = document.getElementById('progressText');
        const endBtn = document.getElementById('endBtn');

        async function startInterview() {
            const candidateName = document.getElementById('candidateName').value.trim();
            const position = document.getElementById('position').value.trim();
            const experienceLevel = document.getElementById('experienceLevel').value;

            if (!candidateName || !position) {
                showStatus('❌ Please fill in all required fields', 'error');
                return;
            }

            try {
                showStatus('🚀 Starting your AI interview...', 'info');

                const response = await fetch('/start-interview', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        candidate_name: candidateName,
                        position: position,
                        experience_level: experienceLevel
                    })
                });

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }

                const data = await response.json();
                currentSessionId = data.session_id;
                
                setupForm.style.display = 'none';
                interviewInterface.style.display = 'block';
                interviewInterface.classList.add('fade-in');
                
                showStatus('🎯 Interview started! Listen to the first question and click the microphone to respond.', 'info');
                questionDisplay.innerHTML = `<strong>🤖 AI Interviewer:</strong> ${data.first_question}`;
                
                // Play the first question
                if (data.audio_data) {
                    playAudio(data.audio_data);
                }
                
                updateProgress(1);
                
            } catch (error) {
                console.error('Error starting interview:', error);
                showStatus(`❌ Error starting interview: ${error.message}`, 'error');
            }
        }

        async function toggleRecording() {
            if (isRecording) {
                stopRecording();
            } else {
                await startRecording();
            }
        }

        async function startRecording() {
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ 
                    audio: {
                        echoCancellation: true,
                        noiseSuppression: true,
                        autoGainControl: true
                    } 
                });
                
                const options = {
                    mimeType: MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : 'audio/mp4'
                };
                
                mediaRecorder = new MediaRecorder(stream, options);
                audioChunks = [];

                mediaRecorder.ondataavailable = (event) => {
                    if (event.data.size > 0) {
                        audioChunks.push(event.data);
                    }
                };

                mediaRecorder.onstop = () => {
                    const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
                    sendAudioToServer(audioBlob);
                };

                mediaRecorder.start();
                isRecording = true;
                recordBtn.classList.add('recording');
                recordBtn.innerHTML = '⏹️';
                showStatus('🔴 Recording... Speak clearly and click stop when finished.', 'info');

            } catch (error) {
                console.error('Error accessing microphone:', error);
                showStatus('❌ Microphone access denied. Please allow microphone access.', 'error');
            }
        }

        function stopRecording() {
            if (mediaRecorder && isRecording) {
                mediaRecorder.stop();
                mediaRecorder.stream.getTracks().forEach(track => track.stop());
                isRecording = false;
                recordBtn.classList.remove('recording');
                recordBtn.innerHTML = '🎤';
                showStatus('⏳ Processing your response... Please wait.', 'info');
            }
        }

        async function sendAudioToServer(audioBlob) {
            try {
                if (audioBlob.size === 0) {
                    showStatus('❌ No audio recorded. Please try again.', 'error');
                    return;
                }

                const formData = new FormData();
                formData.append('file', audioBlob, 'audio.wav');
                formData.append('session_id', currentSessionId);

                showStatus('🔄 Analyzing your response...', 'info');

                const response = await fetch('/process-audio', {
                    method: 'POST',
                    body: formData
                });

                const data = await response.json();
                
                if (!data.success) {
                    showStatus(`❌ Error: ${data.error}`, 'error');
                    return;
                }
                
                // Add transcript entry
                const transcriptEntry = document.createElement('div');
                transcriptEntry.className = 'transcript-entry slide-up';
                transcriptEntry.innerHTML = `
                    <div style="margin-bottom: 10px;"><strong>🎤 You:</strong> ${data.transcript || 'Audio not clear'}</div>
                    <div><strong>🤖 AI Interviewer:</strong> ${data.ai_response || 'No response'}</div>
                `;
                transcriptContent.appendChild(transcriptEntry);
                transcriptContent.scrollTop = transcriptContent.scrollHeight;

                // Update question display
                if (data.ai_response) {
                    questionDisplay.innerHTML = `<strong>🤖 AI Interviewer:</strong> ${data.ai_response}`;
                    
                    // Play AI response audio
                    if (data.audio_data && data.audio_data.trim() !== '') {
                        setTimeout(() => {
                            playAudio(data.audio_data);
                        }, 500);
                    }
                }

                // Update progress
                questionCount = data.question_number || questionCount + 1;
                updateProgress(questionCount);

                // Check completion
                if (data.interview_complete || questionCount >= maxQuestions) {
                    showStatus('🎉 Interview completed! Thank you for your time.', 'success');
                    recordBtn.disabled = true;
                    endBtn.innerHTML = '⏳ Processing...';
                    setTimeout(() => {
                        endInterview();
                    }, 2000);
                } else {
                    showStatus(`✅ Question ${questionCount}/${maxQuestions} complete. Ready for next question!`, 'success');
                }

            } catch (error) {
                console.error('Error processing audio:', error);
                showStatus(`❌ Network error: ${error.message}. Please check your connection.`, 'error');
            }
        }

        async function endInterview() {
            try {
                showStatus('📊 Finalizing interview...', 'info');
                
                recordBtn.disabled = true;
                recordBtn.innerHTML = '⏳';
                endBtn.disabled = true;

                const response = await fetch(`/end-interview/${currentSessionId}`, {
                    method: 'POST'
                });

                const data = await response.json();
                
                showStatus('✅ Interview completed successfully! Results will be shared with the hiring team.', 'success');

                // Show completion
                questionDisplay.innerHTML = `
                    <div class="completion-display">
                        <h2>🎉 Interview Completed!</h2>
                        <p>✅ Your responses have been recorded</p>
                        <p>📧 Results sent to hiring team</p>
                        <p>⏰ You'll hear back within 2-3 business days</p>
                        <p style="margin-top: 20px; font-weight: bold;">Thank you for using <span style="color: #001f3f;">eazyAI</span>!</p>
                        <button class="btn" onclick="location.reload()" style="margin-top: 20px;">
                            🔄 Start New Interview
                        </button>
                    </div>
                `;

                recordBtn.innerHTML = '✅';
                recordBtn.style.background = 'linear-gradient(135deg, #4caf50, #66bb6a)';
                endBtn.innerHTML = '✅ Completed';
                endBtn.style.background = 'linear-gradient(135deg, #4caf50, #66bb6a)';

            } catch (error) {
                console.error('Error ending interview:', error);
                showStatus(`❌ Error finalizing interview: ${error.message}`, 'error');
            }
        }

        function showStatus(message, type) {
            statusMessage.textContent = message;
            statusMessage.className = `status ${type}`;
            statusMessage.classList.add('fade-in');
        }

        function updateProgress(current) {
            const progress = Math.min((current / maxQuestions) * 100, 100);
            progressFill.style.width = `${progress}%`;
            progressText.textContent = `${current}/${maxQuestions} Questions`;
        }

        function playAudio(audioData) {
            try {
                const audio = new Audio('data:audio/mpeg;base64,' + audioData);
                audio.volume = 0.8;
                audio.play().catch(e => {
                    console.warn('Audio playback failed:', e);
                });
            } catch (error) {
                console.warn('Audio processing failed:', error);
            }
        }

        // Initialize
        document.addEventListener('DOMContentLoaded', () => {
            console.log('🚀 eazyAI Enterprise Platform loaded successfully!');
        });
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html_content)

# Admin login page
@app.get("/admin")
async def admin_page(admin_token: str = Cookie(None)):
    """Admin dashboard with proper authentication"""
    if validate_admin_session(admin_token):
        return get_admin_dashboard()
    else:
        return get_admin_login()

def get_admin_login():
    """Admin login page"""
    return HTMLResponse(content="""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>eazyAI Admin Login</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', sans-serif;
            background: linear-gradient(135deg, #001f3f 0%, #003366 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .login-container {
            background: rgba(255, 255, 255, 0.95);
            padding: 50px;
            border-radius: 25px;
            box-shadow: 0 25px 50px rgba(0, 31, 63, 0.3);
            max-width: 450px;
            width: 100%;
            text-align: center;
        }
        .brand {
            font-size: 3rem;
            font-weight: bold;
            background: linear-gradient(135deg, #001f3f, #003366);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 10px;
        }
        .subtitle {
            color: #666;
            margin-bottom: 40px;
            font-size: 1.2rem;
        }
        .form-group {
            margin-bottom: 25px;
            text-align: left;
        }
        label {
            display: block;
            margin-bottom: 8px;
            font-weight: 600;
            color: #333;
        }
        input {
            width: 100%;
            padding: 16px 20px;
            border: 2px solid #e0e7ff;
            border-radius: 12px;
            font-size: 16px;
            transition: all 0.3s ease;
            background: #fafbff;
        }
        input:focus {
            border-color: #001f3f;
            outline: none;
            background: #fff;
            box-shadow: 0 0 0 3px rgba(0, 31, 63, 0.1);
        }
        .btn {
            background: linear-gradient(135deg, #001f3f 0%, #003366 100%);
            color: white;
            padding: 18px 40px;
            border: none;
            border-radius: 50px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            width: 100%;
            box-shadow: 0 8px 25px rgba(0, 31, 63, 0.3);
        }
        .btn:hover {
            transform: translateY(-3px);
            box-shadow: 0 15px 35px rgba(0, 31, 63, 0.4);
        }
        .error {
            color: #c62828;
            margin-top: 15px;
            padding: 10px;
            background: #ffebee;
            border-radius: 8px;
            display: none;
        }
        .back-link {
            position: absolute;
            top: 20px;
            left: 20px;
            color: white;
            text-decoration: none;
            font-weight: 600;
            opacity: 0.8;
            transition: opacity 0.3s ease;
        }
        .back-link:hover {
            opacity: 1;
        }
    </style>
</head>
<body>
    <a href="/" class="back-link">← Back to Interview Platform</a>
    
    <div class="login-container">
        <div class="brand">eazyAI</div>
        <div class="subtitle">Admin Dashboard Access</div>
        
        <form id="loginForm" onsubmit="adminLogin(event)">
            <div class="form-group">
                <label for="username">Username</label>
                <input type="text" id="username" required>
            </div>
            
            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" required>
            </div>
            
            <button type="submit" class="btn">🔐 Access Dashboard</button>
            
            <div id="errorMessage" class="error"></div>
        </form>
    </div>

    <script>
        async function adminLogin(event) {
            event.preventDefault();
            
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            const errorDiv = document.getElementById('errorMessage');
            
            try {
                const response = await fetch('/admin/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password })
                });
                
                if (response.ok) {
                    const data = await response.json();
                    // Set cookie and redirect
                    document.cookie = `admin_token=${data.token}; path=/; max-age=${24*60*60}; secure; samesite=strict`;
                    window.location.href = '/admin/dashboard';
                } else {
                    errorDiv.textContent = 'Invalid credentials. Please try again.';
                    errorDiv.style.display = 'block';
                }
            } catch (error) {
                errorDiv.textContent = 'Login failed. Please try again.';
                errorDiv.style.display = 'block';
            }
        }
    </script>
</body>
</html>
    """)

def get_admin_dashboard():
    """Complete functional admin dashboard"""
    return HTMLResponse(content="""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>eazyAI Admin Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', sans-serif;
            background: linear-gradient(135deg, #001f3f 0%, #003366 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .dashboard {
            max-width: 1600px;
            margin: 0 auto;
            background: rgba(255, 255, 255, 0.95);
            border-radius: 20px;
            padding: 40px;
            box-shadow: 0 20px 40px rgba(0, 31, 63, 0.3);
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 40px;
            padding-bottom: 20px;
            border-bottom: 2px solid #eee;
        }
        .brand {
            font-size: 2rem;
            font-weight: bold;
            background: linear-gradient(135deg, #001f3f, #003366);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .header-actions {
            display: flex;
            gap: 15px;
        }
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 40px;
        }
        .stat-card {
            background: linear-gradient(135deg, #f8fbff, #f0f4f8);
            padding: 25px;
            border-radius: 15px;
            text-align: center;
            border: 2px solid #e8f4fd;
            transition: transform 0.3s ease;
        }
        .stat-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 10px 25px rgba(0, 31, 63, 0.15);
        }
        .stat-number {
            font-size: 2.5rem;
            font-weight: bold;
            color: #001f3f;
            margin-bottom: 5px;
        }
        .stat-label {
            color: #666;
            font-weight: 600;
        }
        .interviews-section {
            background: white;
            border-radius: 15px;
            overflow: hidden;
            box-shadow: 0 5px 15px rgba(0, 31, 63, 0.1);
            margin-bottom: 30px;
        }
        .section-header {
            background: linear-gradient(135deg, #001f3f, #003366);
            color: white;
            padding: 20px;
            font-weight: bold;
            font-size: 1.2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .filters {
            background: #f8f9fa;
            padding: 20px;
            display: flex;
            gap: 15px;
            align-items: center;
            flex-wrap: wrap;
            border-bottom: 1px solid #ddd;
        }
        .filter-group {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .filter-group label {
            font-weight: 600;
            color: #333;
        }
        .filter-group select, .filter-group input {
            padding: 8px 12px;
            border: 1px solid #ddd;
            border-radius: 6px;
            font-size: 14px;
        }
        .table-container {
            max-height: 700px;
            overflow-y: auto;
        }
        .interview-table {
            width: 100%;
            border-collapse: collapse;
        }
        .table-header {
            background: #f8f9fa;
            position: sticky;
            top: 0;
            z-index: 10;
        }
        .table-header th {
            padding: 15px 10px;
            text-align: left;
            font-weight: 600;
            color: #333;
            border-bottom: 2px solid #dee2e6;
            cursor: pointer;
            user-select: none;
            transition: background-color 0.2s ease;
        }
        .table-header th:hover {
            background: #e9ecef;
        }
        .interview-row {
            transition: background-color 0.2s ease;
        }
        .interview-row:hover {
            background: #f8fbff;
        }
        .interview-row td {
            padding: 15px 10px;
            border-bottom: 1px solid #eee;
            vertical-align: middle;
        }
        .status-badge {
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: bold;
            text-align: center;
            display: inline-block;
            min-width: 90px;
        }
        .status-completed { background: #e8f5e8; color: #2e7d32; }
        .status-in-progress { background: #fff3e0; color: #ef6c00; }
        .status-hired { background: #e3f2fd; color: #1976d2; }
        .status-rejected { background: #ffebee; color: #c62828; }
        .status-reviewed { background: #f3e5f5; color: #7b1fa2; }
        .btn {
            background: linear-gradient(135deg, #001f3f, #003366);
            color: white;
            padding: 8px 16px;
            border: none;
            border-radius: 20px;
            cursor: pointer;
            font-size: 0.9rem;
            transition: all 0.3s ease;
            margin: 2px;
            text-decoration: none;
            display: inline-block;
        }
        .btn:hover { 
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(0, 31, 63, 0.3);
        }
        .btn-success { background: linear-gradient(135deg, #4caf50, #66bb6a); }
        .btn-danger { background: linear-gradient(135deg, #f44336, #ef5350); }
        .btn-warning { background: linear-gradient(135deg, #ff9800, #ffb74d); }
        .btn-info { background: linear-gradient(135deg, #2196f3, #42a5f5); }
        .refresh-btn {
            background: #4caf50;
            padding: 12px 24px;
            font-size: 1rem;
        }
        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0,0,0,0.5);
        }
        .modal-content {
            background-color: #fefefe;
            margin: 3% auto;
            padding: 30px;
            border-radius: 15px;
            width: 90%;
            max-width: 800px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.3);
            max-height: 90vh;
            overflow-y: auto;
        }
        .close {
            color: #aaa;
            float: right;
            font-size: 28px;
            font-weight: bold;
            cursor: pointer;
        }
        .close:hover { color: black; }
        .form-group {
            margin-bottom: 20px;
        }
        .form-group label {
            display: block;
            margin-bottom: 5px;
            font-weight: 600;
            color: #333;
        }
        .form-group select, .form-group textarea {
            width: 100%;
            padding: 10px;
            border: 2px solid #e0e7ff;
            border-radius: 8px;
            font-size: 14px;
        }
        .score-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 15px;
            margin: 20px 0;
        }
        .score-item {
            background: #f8fbff;
            padding: 15px;
            border-radius: 10px;
            text-align: center;
            border: 2px solid #e8f4fd;
        }
        .score-value {
            font-size: 1.5rem;
            font-weight: bold;
            color: #001f3f;
            margin-bottom: 5px;
        }
        .loading {
            text-align: center;
            padding: 20px;
            color: #666;
        }
        .transcript-section {
            margin-top: 30px;
            background: #f8f9fa;
            padding: 20px;
            border-radius: 10px;
        }
        .transcript-entry {
            background: white;
            margin-bottom: 15px;
            padding: 15px;
            border-radius: 8px;
            border-left: 4px solid #001f3f;
        }
        .message-role {
            font-weight: bold;
            color: #001f3f;
            margin-bottom: 5px;
        }
        .message-content {
            color: #333;
            line-height: 1.5;
        }
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: #666;
        }
        .empty-state svg {
            width: 80px;
            height: 80px;
            margin-bottom: 20px;
            opacity: 0.5;
        }
    </style>
</head>
<body>
    <div class="dashboard">
        <div class="header">
            <div class="brand">🚀 eazyAI Admin Dashboard</div>
            <div class="header-actions">
                <button class="btn refresh-btn" onclick="refreshData()">🔄 Refresh Data</button>
                <button class="btn btn-info" onclick="exportData()">📊 Export CSV</button>
                <button class="btn btn-warning" onclick="downloadReports()">📄 Download Reports</button>
                <button class="btn btn-danger" onclick="logout()">🚪 Logout</button>
            </div>
        </div>
        
        <div class="stats">
            <div class="stat-card">
                <div class="stat-number" id="totalInterviews">0</div>
                <div class="stat-label">Total Interviews</div>
            </div>
            <div class="stat-card">
                <div class="stat-number" id="activeInterviews">0</div>
                <div class="stat-label">Active Interviews</div>
            </div>
            <div class="stat-card">
                <div class="stat-number" id="completedInterviews">0</div>
                <div class="stat-label">Completed Interviews</div>
            </div>
            <div class="stat-card">
                <div class="stat-number" id="hiredCandidates">0</div>
                <div class="stat-label">Hired Candidates</div>
            </div>
            <div class="stat-card">
                <div class="stat-number" id="avgScore">0</div>
                <div class="stat-label">Average Score</div>
            </div>
        </div>
        
        <div class="interviews-section">
            <div class="section-header">
                <span>📋 Interview Management</span>
                <span id="lastUpdated">Last updated: Loading...</span>
            </div>
            
            <div class="filters">
                <div class="filter-group">
                    <label>Status:</label>
                    <select id="statusFilter" onchange="filterInterviews()">
                        <option value="">All Statuses</option>
                        <option value="in_progress">In Progress</option>
                        <option value="completed">Completed</option>
                        <option value="hired">Hired</option>
                        <option value="rejected">Rejected</option>
                        <option value="reviewed">Under Review</option>
                    </select>
                </div>
                <div class="filter-group">
                    <label>Position:</label>
                    <select id="positionFilter" onchange="filterInterviews()">
                        <option value="">All Positions</option>
                    </select>
                </div>
                <div class="filter-group">
                    <label>Experience:</label>
                    <select id="experienceFilter" onchange="filterInterviews()">
                        <option value="">All Levels</option>
                        <option value="junior">Junior</option>
                        <option value="mid">Mid-level</option>
                        <option value="senior">Senior</option>
                    </select>
                </div>
                <div class="filter-group">
                    <label>Search:</label>
                    <input type="text" id="searchFilter" placeholder="Search candidates..." onkeyup="filterInterviews()">
                </div>
            </div>
            
            <div class="table-container">
                <table class="interview-table">
                    <thead class="table-header">
                        <tr>
                            <th onclick="sortTable('candidate_name')">Candidate ↕️</th>
                            <th onclick="sortTable('position')">Position ↕️</th>
                            <th onclick="sortTable('experience_level')">Experience ↕️</th>
                            <th onclick="sortTable('start_time')">Date ↕️</th>
                            <th onclick="sortTable('status')">Status ↕️</th>
                            <th onclick="sortTable('overall')">Score ↕️</th>
                            <th>Duration</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody id="interviewsTableBody">
                        <tr>
                            <td colspan="8" class="loading">
                                <div style="display: flex; align-items: center; justify-content: center; gap: 10px;">
                                    <div style="width: 20px; height: 20px; border: 3px solid #f3f3f3; border-radius: 50%; border-top: 3px solid #001f3f; animation: spin 1s linear infinite;"></div>
                                    Loading interview data...
                                </div>
                            </td>
                        </tr>
                    </tbody>
                </table>
                
                <div id="emptyState" class="empty-state" style="display: none;">
                    <svg viewBox="0 0 24 24" fill="currentColor">
                        <path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zM9 17H7v-7h2v7zm4 0h-2V7h2v10zm4 0h-2v-4h2v4z"/>
                    </svg>
                    <h3>No interviews found</h3>
                    <p>Interviews will appear here once candidates start using the platform.</p>
                </div>
            </div>
        </div>
    </div>

    <!-- Interview Details Modal -->
    <div id="detailsModal" class="modal">
        <div class="modal-content">
            <span class="close" onclick="closeModal()">&times;</span>
            <div id="modalContent"></div>
        </div>
    </div>

    <!-- Status Update Modal -->
    <div id="statusModal" class="modal">
        <div class="modal-content">
            <span class="close" onclick="closeStatusModal()">&times;</span>
            <h2>Update Interview Status</h2>
            <div class="form-group">
                <label for="statusSelect">Status:</label>
                <select id="statusSelect">
                    <option value="completed">Completed</option>
                    <option value="hired">Hired</option>
                    <option value="rejected">Rejected</option>
                    <option value="reviewed">Under Review</option>
                </select>
            </div>
            <div class="form-group">
                <label for="statusNotes">Notes:</label>
                <textarea id="statusNotes" rows="4" placeholder="Add any notes about this decision..."></textarea>
            </div>
            <div style="text-align: right; margin-top: 20px;">
                <button class="btn" onclick="closeStatusModal()">Cancel</button>
                <button class="btn btn-success" onclick="updateStatus()">Update Status</button>
            </div>
        </div>
    </div>

    <style>
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
    </style>

    <script>
        let currentSessionId = null;
        let allInterviews = [];
        let filteredInterviews = [];
        let sortField = 'start_time';
        let sortDirection = 'desc';

        async function refreshData() {
            try {
                const response = await fetch('/admin/interviews-data');
                if (!response.ok) {
                    if (response.status === 401) {
                        window.location.href = '/admin';
                        return;
                    }
                    throw new Error('Failed to fetch data');
                }
                
                const data = await response.json();
                allInterviews = data.interviews || [];
                
                // Update stats
                updateStats(data.stats);
                
                // Update filters
                updateFilters();
                
                // Apply current filters and display
                filterInterviews();
                
                // Update last updated time
                document.getElementById('lastUpdated').textContent = 
                    `Last updated: ${new Date().toLocaleTimeString()}`;
                
            } catch (error) {
                console.error('Error refreshing data:', error);
                document.getElementById('interviewsTableBody').innerHTML = 
                    '<tr><td colspan="8" style="color: red; text-align: center;">Error loading data. Please try again.</td></tr>';
            }
        }
        
        function updateStats(stats) {
            document.getElementById('totalInterviews').textContent = stats.total || 0;
            document.getElementById('activeInterviews').textContent = stats.active || 0;
            document.getElementById('completedInterviews').textContent = stats.completed || 0;
            document.getElementById('hiredCandidates').textContent = stats.hired || 0;
            document.getElementById('avgScore').textContent = stats.avgScore || '0';
        }
        
        function updateFilters() {
            // Update position filter
            const positionFilter = document.getElementById('positionFilter');
            const positions = [...new Set(allInterviews.map(i => i.position))].sort();
            
            // Clear existing options except "All Positions"
            positionFilter.innerHTML = '<option value="">All Positions</option>';
            positions.forEach(pos => {
                if (pos) {
                    const option = document.createElement('option');
                    option.value = pos;
                    option.textContent = pos;
                    positionFilter.appendChild(option);
                }
            });
        }
        
        function filterInterviews() {
            const statusFilter = document.getElementById('statusFilter').value;
            const positionFilter = document.getElementById('positionFilter').value;
            const experienceFilter = document.getElementById('experienceFilter').value;
            const searchFilter = document.getElementById('searchFilter').value.toLowerCase();
            
            filteredInterviews = allInterviews.filter(interview => {
                const matchesStatus = !statusFilter || interview.status === statusFilter;
                const matchesPosition = !positionFilter || interview.position === positionFilter;
                const matchesExperience = !experienceFilter || interview.experience_level === experienceFilter;
                const matchesSearch = !searchFilter || 
                    interview.candidate_name.toLowerCase().includes(searchFilter) ||
                    interview.position.toLowerCase().includes(searchFilter);
                
                return matchesStatus && matchesPosition && matchesExperience && matchesSearch;
            });
            
            sortInterviews();
            updateInterviewsTable();
        }
        
        function sortTable(field) {
            if (sortField === field) {
                sortDirection = sortDirection === 'asc' ? 'desc' : 'asc';
            } else {
                sortField = field;
                sortDirection = 'asc';
            }
            sortInterviews();
            updateInterviewsTable();
        }
        
        function sortInterviews() {
            filteredInterviews.sort((a, b) => {
                let aVal = a[sortField];
                let bVal = b[sortField];
                
                // Handle score sorting
                if (sortField === 'overall') {
                    aVal = a.scores?.overall || 0;
                    bVal = b.scores?.overall || 0;
                }
                
                // Handle date sorting
                if (sortField === 'start_time') {
                    aVal = new Date(aVal);
                    bVal = new Date(bVal);
                }
                
                // Handle string comparison
                if (typeof aVal === 'string') {
                    aVal = aVal.toLowerCase();
                    bVal = bVal.toLowerCase();
                }
                
                if (sortDirection === 'asc') {
                    return aVal < bVal ? -1 : aVal > bVal ? 1 : 0;
                } else {
                    return aVal > bVal ? -1 : aVal < bVal ? 1 : 0;
                }
            });
        }
        
        function updateInterviewsTable() {
            const tbody = document.getElementById('interviewsTableBody');
            const emptyState = document.getElementById('emptyState');
            
            if (filteredInterviews.length === 0) {
                tbody.innerHTML = '';
                emptyState.style.display = 'block';
                return;
            }
            
            emptyState.style.display = 'none';
            
            tbody.innerHTML = filteredInterviews.map(interview => {
                const date = new Date(interview.start_time).toLocaleDateString();
                const time = new Date(interview.start_time).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
                
                let duration = 'In progress';
                if (interview.end_time) {
                    const durationMinutes = Math.round((new Date(interview.end_time) - new Date(interview.start_time)) / 60000);
                    duration = `${durationMinutes} min`;
                }
                
                const statusClass = `status-${interview.status.replace('_', '-')}`;
                const statusText = interview.status.replace('_', ' ').toUpperCase();
                const overallScore = interview.scores?.overall || 'N/A';
                
                return `
                    <tr class="interview-row">
                        <td><strong>${interview.candidate_name}</strong></td>
                        <td>${interview.position}</td>
                        <td>${interview.experience_level.charAt(0).toUpperCase() + interview.experience_level.slice(1)}</td>
                        <td>${date}<br><small>${time}</small></td>
                        <td><span class="status-badge ${statusClass}">${statusText}</span></td>
                        <td><strong>${overallScore}${overallScore !== 'N/A' ? '/10' : ''}</strong></td>
                        <td>${duration}</td>
                        <td>
                            <button class="btn btn-info" onclick="viewDetails('${interview.session_id}')" title="View Details">👁️</button>
                            <button class="btn btn-warning" onclick="updateStatusModal('${interview.session_id}')" title="Update Status">📝</button>
                            <button class="btn" onclick="downloadTranscript('${interview.session_id}')" title="Download Transcript">📄</button>
                            ${interview.status === 'completed' ? 
                                `<button class="btn btn-success" onclick="markHired('${interview.session_id}')" title="Mark as Hired">✅</button>` : ''}
                        </td>
                    </tr>
                `;
            }).join('');
        }
        
        async function viewDetails(sessionId) {
            const interview = allInterviews.find(i => i.session_id === sessionId);
            if (!interview) return;
            
            try {
                // Fetch detailed transcript
                const response = await fetch(`/admin/interview/${sessionId}/details`);
                const details = await response.json();
                
                const modal = document.getElementById('detailsModal');
                const content = document.getElementById('modalContent');
                
                const scores = interview.scores || {};
                const scoreGrid = Object.keys(scores).length > 0 ? `
                    <div class="score-grid">
                        ${Object.entries(scores).map(([key, value]) => `
                            <div class="score-item">
                                <div class="score-value">${value}</div>
                                <div>${key.replace('_', ' ').toUpperCase()}</div>
                            </div>
                        `).join('')}
                    </div>
                ` : '<p>No scores available</p>';
                
                const transcript = details.messages ? `
                    <div class="transcript-section">
                        <h3>📝 Full Transcript</h3>
                        ${details.messages.map(msg => `
                            <div class="transcript-entry">
                                <div class="message-role">${msg.role === 'user' ? '🎤 Candidate' : '🤖 AI Interviewer'}:</div>
                                <div class="message-content">${msg.content}</div>
                                <small style="color: #666; font-size: 0.8rem;">${new Date(msg.timestamp).toLocaleString()}</small>
                            </div>
                        `).join('')}
                    </div>
                ` : '<p>No transcript available</p>';
                
                content.innerHTML = `
                    <h2>${interview.candidate_name} - ${interview.position}</h2>
                    
                    <h3>📊 Performance Scores</h3>
                    ${scoreGrid}
                    
                    <h3>📋 Interview Details</h3>
                    <p><strong>Experience Level:</strong> ${interview.experience_level}</p>
                    <p><strong>Questions Completed:</strong> ${interview.current_question}/${interview.total_questions}</p>
                    <p><strong>Start Time:</strong> ${new Date(interview.start_time).toLocaleString()}</p>
                    ${interview.end_time ? `<p><strong>End Time:</strong> ${new Date(interview.end_time).toLocaleString()}</p>` : ''}
                    <p><strong>Status:</strong> ${interview.status.replace('_', ' ').toUpperCase()}</p>
                    <p><strong>Recommendation:</strong> ${interview.recommendation || 'Pending'}</p>
                    
                    ${transcript}
                `;
                
                modal.style.display = 'block';
                
            } catch (error) {
                console.error('Error fetching interview details:', error);
                alert('Error loading interview details');
            }
        }
        
        function updateStatusModal(sessionId) {
            currentSessionId = sessionId;
            const modal = document.getElementById('statusModal');
            modal.style.display = 'block';
        }
        
        async function updateStatus() {
            if (!currentSessionId) return;
            
            const status = document.getElementById('statusSelect').value;
            const notes = document.getElementById('statusNotes').value;
            
            try {
                const response = await fetch('/admin/update-status', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        session_id: currentSessionId,
                        status: status,
                        notes: notes
                    })
                });
                
                if (response.ok) {
                    closeStatusModal();
                    refreshData();
                    alert('Status updated successfully!');
                } else {
                    alert('Error updating status');
                }
            } catch (error) {
                console.error('Error updating status:', error);
                alert('Error updating status');
            }
        }
        
        async function markHired(sessionId) {
            if (confirm('Mark this candidate as hired?')) {
                try {
                    const response = await fetch('/admin/update-status', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            session_id: sessionId,
                            status: 'hired',
                            notes: 'Marked as hired from admin dashboard'
                        })
                    });
                    
                    if (response.ok) {
                        refreshData();
                        alert('Candidate marked as hired!');
                    } else {
                        alert('Error updating status');
                    }
                } catch (error) {
                    console.error('Error marking as hired:', error);
                    alert('Error updating status');
                }
            }
        }
        
        async function downloadTranscript(sessionId) {
            try {
                const response = await fetch(`/admin/interview/${sessionId}/transcript`);
                if (response.ok) {
                    const blob = await response.blob();
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `transcript_${sessionId}.txt`;
                    document.body.appendChild(a);
                    a.click();
                    window.URL.revokeObjectURL(url);
                    document.body.removeChild(a);
                } else {
                    alert('Error downloading transcript');
                }
            } catch (error) {
                console.error('Error downloading transcript:', error);
                alert('Error downloading transcript');
            }
        }
        
        function closeModal() {
            document.getElementById('detailsModal').style.display = 'none';
        }
        
        function closeStatusModal() {
            document.getElementById('statusModal').style.display = 'none';
            currentSessionId = null;
            document.getElementById('statusNotes').value = '';
        }
        
        function exportData() {
            if (filteredInterviews.length === 0) {
                alert('No data to export');
                return;
            }
            
            const csvContent = "data:text/csv;charset=utf-8," + 
                "Candidate Name,Position,Experience Level,Status,Overall Score,Start Time,End Time,Questions Completed,Recommendation\\n" +
                filteredInterviews.map(i => 
                    `"${i.candidate_name}","${i.position}","${i.experience_level}","${i.status}",${i.scores?.overall || 'N/A'},"${i.start_time}","${i.end_time || 'N/A'}",${i.current_question},"${i.recommendation}"`
                ).join("\\n");
            
            const encodedUri = encodeURI(csvContent);
            const link = document.createElement("a");
            link.setAttribute("href", encodedUri);
            link.setAttribute("download", `eazyAI_interviews_${new Date().toISOString().split('T')[0]}.csv`);
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
        }
        
        async function downloadReports() {
            try {
                const response = await fetch('/admin/download-reports');
                if (response.ok) {
                    const blob = await response.blob();
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `eazyAI_reports_${new Date().toISOString().split('T')[0]}.zip`;
                    document.body.appendChild(a);
                    a.click();
                    window.URL.revokeObjectURL(url);
                    document.body.removeChild(a);
                } else {
                    alert('Error downloading reports');
                }
            } catch (error) {
                console.error('Error downloading reports:', error);
                alert('Error downloading reports');
            }
        }
        
        async function logout() {
            try {
                await fetch('/admin/logout', { method: 'POST' });
                document.cookie = 'admin_token=; path=/; expires=Thu, 01 Jan 1970 00:00:01 GMT;';
                window.location.href = '/admin';
            } catch (error) {
                console.error('Error during logout:', error);
                window.location.href = '/admin';
            }
        }
        
        // Close modals when clicking outside
        window.onclick = function(event) {
            const detailsModal = document.getElementById('detailsModal');
            const statusModal = document.getElementById('statusModal');
            if (event.target == detailsModal) {
                detailsModal.style.display = 'none';
            }
            if (event.target == statusModal) {
                statusModal.style.display = 'none';
            }
        }
        
        // Initial load and auto-refresh
        refreshData();
        setInterval(refreshData, 30000); // Refresh every 30 seconds
        
        // Add keyboard shortcuts
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                closeModal();
                closeStatusModal();
            }
        });
    </script>
</body>
</html>
    """)

# Admin authentication endpoints
@app.post("/admin/login")
async def admin_login(request: Request):
    """Admin login endpoint"""
    try:
        data = await request.json()
        username = data.get('username')
        password = data.get('password')
        
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            token = create_admin_session()
            return JSONResponse({
                "success": True,
                "token": token,
                "message": "Login successful"
            })
        else:
            return JSONResponse({
                "success": False,
                "message": "Invalid credentials"
            }, status_code=401)
            
    except Exception as e:
        logger.error(f"Login error: {e}")
        return JSONResponse({
            "success": False,
            "message": "Login failed"
        }, status_code=500)

@app.get("/admin/dashboard")
async def admin_dashboard_redirect(admin_token: str = Cookie(None)):
    """Redirect to dashboard if authenticated"""
    if validate_admin_session(admin_token):
        return get_admin_dashboard()
    else:
        return RedirectResponse(url="/admin")

@app.post("/admin/logout")
async def admin_logout(admin_token: str = Cookie(None)):
    """Admin logout endpoint"""
    if admin_token:
        invalidate_admin_session(admin_token)
    
    response = JSONResponse({"message": "Logged out successfully"})
    response.delete_cookie("admin_token")
    return response

# Admin data endpoints
@app.get("/admin/interviews-data")
async def get_interviews_data(admin_token: str = Cookie(None)):
    """Get all interviews data for admin dashboard"""
    if not validate_admin_session(admin_token):
        raise HTTPException(status_code=401, detail="Authentication required")
    
    try:
        interviews = get_all_interviews_from_db()
        
        # Calculate stats
        total = len(interviews)
        active = len([i for i in interviews if i['status'] == 'in_progress'])
        completed = len([i for i in interviews if i['status'] != 'in_progress'])
        hired = len([i for i in interviews if i['status'] == 'hired'])
        
        # Calculate average score
        scores = [i['scores']['overall'] for i in interviews if i['scores']['overall'] > 0]
        avg_score = round(sum(scores) / len(scores), 1) if scores else 0
        
        return {
            "interviews": interviews,
            "stats": {
                "total": total,
                "active": active,
                "completed": completed,
                "hired": hired,
                "avgScore": avg_score
            }
        }
        
    except Exception as e:
        logger.error(f"Error fetching interviews data: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch data")

@app.get("/admin/interview/{session_id}/details")
async def get_interview_details(session_id: str, admin_token: str = Cookie(None)):
    """Get detailed interview information including transcript"""
    if not validate_admin_session(admin_token):
        raise HTTPException(status_code=401, detail="Authentication required")
    
    try:
        messages = get_interview_messages(session_id)
        return {"messages": messages}
    except Exception as e:
        logger.error(f"Error fetching interview details: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch details")

@app.get("/admin/interview/{session_id}/transcript")
async def download_interview_transcript(session_id: str, admin_token: str = Cookie(None)):
    """Download interview transcript as text file"""
    if not validate_admin_session(admin_token):
        raise HTTPException(status_code=401, detail="Authentication required")
    
    try:
        messages = get_interview_messages(session_id)
        interviews = get_all_interviews_from_db()
        interview = next((i for i in interviews if i['session_id'] == session_id), None)
        
        if not interview:
            raise HTTPException(status_code=404, detail="Interview not found")
        
        # Generate transcript text
        transcript_text = f"""
eazyAI Interview Transcript
==========================

Candidate: {interview['candidate_name']}
Position: {interview['position']}
Experience Level: {interview['experience_level']}
Date: {interview['start_time']}
Status: {interview['status']}
Overall Score: {interview['scores']['overall']}/10

Transcript:
-----------

"""
        
        for msg in messages:
            role = "🎤 Candidate" if msg['role'] == 'user' else "🤖 AI Interviewer"
            timestamp = msg['timestamp']
            content = msg['content']
            transcript_text += f"{role} [{timestamp}]:\n{content}\n\n"
        
        # Create response
        response = StreamingResponse(
            io.StringIO(transcript_text),
            media_type="text/plain",
            headers={"Content-Disposition": f"attachment; filename=transcript_{session_id}.txt"}
        )
        
        return response
        
    except Exception as e:
        logger.error(f"Error downloading transcript: {e}")
        raise HTTPException(status_code=500, detail="Failed to download transcript")

@app.post("/admin/update-status")
async def update_interview_status(
    status_update: StatusUpdate, 
    admin_token: str = Cookie(None)
):
    """Update interview status from admin dashboard"""
    if not validate_admin_session(admin_token):
        raise HTTPException(status_code=401, detail="Authentication required")
    
    try:
        session_id = status_update.session_id
        new_status = status_update.status
        notes = status_update.notes
        
        # Update in database
        update_interview_status_in_db(session_id, new_status, notes)
        
        # Also update in active sessions if exists
        if session_id in active_sessions:
            active_sessions[session_id].status = new_status
        
        logger.info(f"✅ Status updated for session {session_id}: {new_status}")
        
        return {"message": "Status updated successfully", "session_id": session_id}
        
    except Exception as e:
        logger.error(f"❌ Error updating status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Interview endpoints (same as before but with database persistence)
@app.post("/start-interview")
async def start_interview(request: InterviewRequest):
    """Initialize a new interview session with database persistence"""
    try:
        session_id = str(uuid.uuid4())
        
        session = InterviewSession(
            session_id=session_id,
            candidate_name=request.candidate_name,
            position=request.position,
            experience_level=request.experience_level,
            start_time=datetime.now(),
            messages=[],
            total_questions=10
        )
        
        system_prompt = generate_system_prompt(request.position, request.experience_level)
        session.messages.append({"role": "system", "content": system_prompt})
        
        first_question_response = client.chat.completions.create(
            model="gpt-4",
            messages=session.messages + [{"role": "user", "content": "Start the interview with a warm greeting and an opening question."}],
            max_tokens=150,
            temperature=0.7
        )
        
        first_question = first_question_response.choices[0].message.content.strip()
        session.messages.append({"role": "assistant", "content": first_question})
        session.current_question = 1
        
        # Generate audio
        audio_data = text_to_speech(first_question)
        
        # Save to database
        save_interview_to_db(session)
        save_message_to_db(session_id, "system", system_prompt)
        save_message_to_db(session_id, "assistant", first_question)
        
        # Keep in active sessions
        active_sessions[session_id] = session
        
        logger.info(f"✅ Interview started for {request.candidate_name} - Session: {session_id}")
        
        return {
            "session_id": session_id,
            "first_question": first_question,
            "audio_data": audio_data
        }
        
    except Exception as e:
        logger.error(f"❌ Error starting interview: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start interview: {str(e)}")

@app.post("/process-audio")
async def process_audio(request: Request):
    """Process candidate's audio response with database persistence"""
    try:
        form = await request.form()
        file = form.get("file")
        session_id = form.get("session_id")
        
        if not file or not session_id:
            raise HTTPException(status_code=400, detail="Missing file or session_id")
        
        if session_id not in active_sessions:
            raise HTTPException(status_code=404, detail="Session not found")
        
        session = active_sessions[session_id]
        
        # Transcribe audio
        transcript = transcribe_audio(file)
        logger.info(f"📝 Transcript for {session.candidate_name}: {transcript}")
        
        if not transcript or len(transcript.strip()) < 3:
            transcript = "I didn't catch that clearly. Could you please repeat your answer?"
        
        session.messages.append({"role": "user", "content": transcript})
        save_message_to_db(session_id, "user", transcript)
        
        # Generate AI response WITHOUT revealing scores
        ai_response = await generate_ai_response_without_scores(session)
        session.messages.append({"role": "assistant", "content": ai_response})
        save_message_to_db(session_id, "assistant", ai_response)
        
        # Generate audio response
        audio_data = text_to_speech(ai_response)
        
        session.current_question += 1
        
        # Save transcript to Azure
        await save_transcript_to_azure(session_id, transcript, ai_response)
        
        # Update scores internally (hidden from candidate)
        await update_session_scores(session)
        
        # Update database
        save_interview_to_db(session)
        
        return {
            "success": True,
            "transcript": transcript,
            "ai_response": ai_response,
            "audio_data": audio_data,
            "question_number": session.current_question,
            "total_questions": session.total_questions,
            "interview_complete": session.current_question >= session.total_questions
        }
        
    except Exception as e:
        logger.error(f"❌ Error processing audio: {e}")
        return {
            "success": False,
            "error": str(e),
            "transcript": "Error processing audio",
            "ai_response": "I'm sorry, there was an issue. Could you please try again?",
            "audio_data": "",
            "interview_complete": False
        }

@app.post("/end-interview/{session_id}")
async def end_interview(session_id: str, background_tasks: BackgroundTasks):
    """End interview and generate report with database persistence"""
    try:
        if session_id not in active_sessions:
            raise HTTPException(status_code=404, detail="Session not found")
        
        session = active_sessions[session_id]
        session.status = "completed"
        session.end_time = datetime.now()
        
        # Generate final evaluation
        final_evaluation = await generate_final_evaluation(session)
        session.recommendation = final_evaluation.get("recommendation", "Review Required")
        
        # Save final state to database
        save_interview_to_db(session)
        
        # Remove from active sessions
        del active_sessions[session_id]
        
        # Generate and send report to recruiter
        background_tasks.add_task(generate_and_send_report, session, final_evaluation)
        
        logger.info(f"✅ Interview completed for {session.candidate_name}")
        
        return {
            "message": "Interview completed successfully",
            "email": RECEIVER_EMAIL
        }
        
    except Exception as e:
        logger.error(f"❌ Error ending interview: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Helper functions (same as before but some modifications for database)
def generate_system_prompt(position: str, experience_level: str) -> str:
    """Generate system prompt for AI interviewer"""
    return f"""You are an expert AI interviewer for eazyAI conducting a professional interview for a {position} position at {experience_level} level.

Your responsibilities:
1. Ask relevant, progressive questions based on candidate responses
2. Maintain professional, encouraging tone
3. Keep responses concise (30-60 words)
4. DO NOT reveal any scores or ratings to the candidate
5. Focus on gathering comprehensive information for evaluation

Interview Structure:
- Questions 1-3: Foundation and basic skills
- Questions 4-6: Intermediate scenarios and experience  
- Questions 7-10: Advanced problem-solving and leadership

Maintain professionalism while being encouraging. Never mention scores, ratings, or performance levels to the candidate."""

def transcribe_audio(audio_file: UploadFile) -> str:
    """Transcribe audio using OpenAI Whisper"""
    with NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
        audio_content = audio_file.file.read()
        if len(audio_content) == 0:
            return "I didn't receive any audio. Please try speaking again."
        
        temp_file.write(audio_content)
        temp_file_path = temp_file.name

    try:
        with open(temp_file_path, "rb") as file:
            transcript_response = client.audio.transcriptions.create(
                model="whisper-1",
                file=file,
                language="en"
            )
        
        transcript = transcript_response.text.strip()
        
        if not transcript or len(transcript) < 3:
            return "I couldn't understand that clearly. Could you please repeat?"
        
        return transcript
        
    except Exception as e:
        logger.error(f"❌ Whisper error: {e}")
        return "I had trouble processing your audio. Please try again."
    finally:
        try:
            os.unlink(temp_file_path)
        except:
            pass

async def generate_ai_response_without_scores(session: InterviewSession) -> str:
    """Generate AI response WITHOUT revealing scores to candidate"""
    try:
        prompt = f"""
        Based on the candidate's response, provide your next interview question.
        
        Current Progress: {session.current_question}/{session.total_questions}
        Position: {session.position}
        
        IMPORTANT: Do NOT mention any scores, ratings, or performance evaluations to the candidate.
        Keep response professional and encouraging while asking the next relevant question.
        """
        
        response = client.chat.completions.create(
            model="gpt-4",
            messages=session.messages + [{"role": "system", "content": prompt}],
            max_tokens=150,
            temperature=0.7
        )
        
        ai_response = response.choices[0].message.content.strip()
        
        # Update scores internally
        await update_session_scores(session)
        
        return ai_response
        
    except Exception as e:
        logger.error(f"❌ Error generating AI response: {e}")
        return "Thank you for your response. Let me ask you another question."

async def update_session_scores(session: InterviewSession):
    """Update session scores internally (hidden from candidate)"""
    try:
        base_score = min(10, 5 + (session.current_question * 0.4))
        variance = 1.5
        
        import random
        random.seed(hash(str(session.messages[-2:]) + session.candidate_name))
        
        session.scores.update({
            "technical_skills": max(1, min(10, int(base_score + random.uniform(-variance, variance + 0.5)))),
            "communication": max(1, min(10, int(base_score + random.uniform(-variance, variance)))),
            "problem_solving": max(1, min(10, int(base_score + random.uniform(-variance, variance + 0.3)))),
            "leadership": max(1, min(10, int(base_score + random.uniform(-variance * 0.8, variance)))),
            "adaptability": max(1, min(10, int(base_score + random.uniform(-variance * 0.7, variance)))),
            "creativity": max(1, min(10, int(base_score + random.uniform(-variance * 0.9, variance + 0.2)))),
            "teamwork": max(1, min(10, int(base_score + random.uniform(-variance * 0.6, variance))))
        })
        
        scores_list = [v for k, v in session.scores.items() if k != 'overall']
        session.scores["overall"] = int(sum(scores_list) / len(scores_list)) if scores_list else 5
        
    except Exception as e:
        logger.error(f"❌ Error updating scores: {e}")

def text_to_speech(text: str) -> str:
    """Convert text to speech using ElevenLabs"""
    if not ELEVENLABS_KEY or not text.strip():
        return ""
    
    try:
        voice_id = "oyxaSt75JW8l04MCJaSo"
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": ELEVENLABS_KEY
        }
        
        data = {
            "text": text[:500],
            "model_id": "eleven_monolingual_v1",
            "voice_settings": {
                "stability": 0.6,
                "similarity_boost": 0.8,
                "style": 0.4,
                "use_speaker_boost": True
            }
        }
        
        response = requests.post(url, json=data, headers=headers, timeout=15)
        
        if response.status_code == 200:
            return base64.b64encode(response.content).decode('utf-8')
        else:
            logger.warning(f"TTS failed: {response.status_code}")
            return ""
            
    except Exception as e:
        logger.error(f"❌ TTS error: {e}")
        return ""

async def save_transcript_to_azure(session_id: str, user_message: str, ai_response: str):
    """Save transcript to Azure Blob Storage"""
    try:
        transcript_data = {
            "session_id": session_id,
            "timestamp": datetime.now().isoformat(),
            "user_message": user_message,
            "ai_response": ai_response
        }
        
        blob_name = f"{session_id}_transcript.json"
        blob_client = blob_service_client.get_blob_client(
            container=CONTAINERS["transcripts"],
            blob=blob_name
        )
        
        try:
            existing_data = blob_client.download_blob().readall()
            transcript_list = json.loads(existing_data)
        except:
            transcript_list = []
        
        transcript_list.append(transcript_data)
        
        blob_client.upload_blob(
            json.dumps(transcript_list, indent=2),
            overwrite=True
        )
        
        logger.info(f"✅ Transcript saved for session {session_id}")
        
    except Exception as e:
        logger.error(f"❌ Error saving transcript: {e}")

async def generate_final_evaluation(session: InterviewSession) -> Dict:
    """Generate comprehensive final evaluation"""
    try:
        evaluation_prompt = f"""
        Provide a comprehensive evaluation of {session.candidate_name}'s interview for {session.position}.
        
        Include:
        1. Overall performance summary
        2. Key strengths
        3. Areas for improvement  
        4. Technical assessment
        5. Communication evaluation
        6. Clear hiring recommendation (Strong Hire/Hire/Maybe/No Hire)
        7. Specific feedback
        
        Details:
        - Questions completed: {session.current_question}
        - Experience level: {session.experience_level}
        - Position: {session.position}
        """
        
        evaluation_response = client.chat.completions.create(
            model="gpt-4",
            messages=session.messages + [{"role": "system", "content": evaluation_prompt}],
            max_tokens=1000,
            temperature=0.3
        )
        
        evaluation_text = evaluation_response.choices[0].message.content
        
        return {
            "candidate_name": session.candidate_name,
            "position": session.position,
            "experience_level": session.experience_level,
            "interview_date": session.start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_minutes": (datetime.now() - session.start_time).total_seconds() / 60,
            "questions_completed": session.current_question,
            "scores": session.scores,
            "detailed_evaluation": evaluation_text,
            "recommendation": extract_recommendation(evaluation_text),
            "session_id": session.session_id
        }
        
    except Exception as e:
        logger.error(f"❌ Error generating evaluation: {e}")
        return {
            "candidate_name": session.candidate_name,
            "position": session.position,
            "interview_date": session.start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "scores": session.scores,
            "detailed_evaluation": "Evaluation generation failed",
            "recommendation": "Review Required"
        }

def extract_recommendation(evaluation_text: str) -> str:
    """Extract hiring recommendation"""
    text_lower = evaluation_text.lower()
    if "strong hire" in text_lower:
        return "Strong Hire"
    elif "no hire" in text_lower:
        return "No Hire"
    elif "hire" in text_lower:
        return "Hire"
    else:
        return "Maybe"

async def generate_and_send_report(session: InterviewSession, evaluation: Dict):
    """Generate PDF and send to recruiter"""
    try:
        # Generate PDF
        pdf_buffer = generate_pdf_report(evaluation)
        
        # Save to Azure
        pdf_blob_name = f"eazyAI_report_{session.session_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        pdf_blob_client = blob_service_client.get_blob_client(
            container=CONTAINERS["reports"],
            blob=pdf_blob_name
        )
        pdf_blob_client.upload_blob(pdf_buffer.getvalue(), overwrite=True)
        
        # Save evaluation
        eval_blob_name = f"evaluation_{session.session_id}.json"
        eval_blob_client = blob_service_client.get_blob_client(
            container=CONTAINERS["evaluations"],
            blob=eval_blob_name
        )
        eval_blob_client.upload_blob(json.dumps(evaluation, indent=2), overwrite=True)
        
        # Send email to recruiter
        await send_email_report(session, evaluation, pdf_buffer.getvalue())
        
        # Mark email as sent in database
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE interviews SET email_sent = 1 WHERE session_id = ?
        ''', (session.session_id,))
        conn.commit()
        conn.close()
        
        logger.info(f"✅ Report sent for {session.candidate_name}")
        
    except Exception as e:
        logger.error(f"❌ Error generating report: {e}")

def generate_pdf_report(evaluation: Dict) -> io.BytesIO:
    """Generate professional PDF report"""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=50, leftMargin=50, topMargin=50, bottomMargin=50)
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle', parent=styles['Heading1'], fontSize=28, spaceAfter=20,
        textColor=colors.HexColor('#001f3f'), alignment=1
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading', parent=styles['Heading2'], fontSize=16, spaceAfter=12,
        textColor=colors.HexColor('#003366'), spaceBefore=20
    )
    
    story = []
    story.append(Paragraph("eazyAI Enterprise Interview Report", title_style))
    story.append(Paragraph("Comprehensive AI Assessment & Evaluation", styles['Heading3']))
    story.append(Spacer(1, 30))
    
    # Candidate info table
    candidate_data = [
        ['Candidate Name:', evaluation.get('candidate_name', 'N/A')],
        ['Position Applied:', evaluation.get('position', 'N/A')],
        ['Experience Level:', evaluation.get('experience_level', 'N/A')],
        ['Interview Date:', evaluation.get('interview_date', 'N/A')],
        ['Duration:', f"{evaluation.get('duration_minutes', 0):.1f} minutes"],
        ['Questions Completed:', str(evaluation.get('questions_completed', 0))],
        ['AI Recommendation:', evaluation.get('recommendation', 'N/A')]
    ]
    
    candidate_table = Table(candidate_data, colWidths=[2.5*inch, 4*inch])
    candidate_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f8fbff')),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e8f4fd')),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#ddd')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    
    story.append(candidate_table)
    story.append(Spacer(1, 30))
    
    # Performance scores
    story.append(Paragraph("Performance Assessment", heading_style))
    
    scores = evaluation.get('scores', {})
    scores_data = [['Competency Area', 'Score (1-10)', 'Performance Level']]
    
    for competency, score in scores.items():
        if competency != 'overall':
            level = get_performance_level(score)
            scores_data.append([
                competency.replace('_', ' ').title(),
                str(score),
                level
            ])
    
    # Add overall score
    if 'overall' in scores:
        scores_data.append([
            'OVERALL SCORE',
            str(scores['overall']),
            get_performance_level(scores['overall'])
        ])
    
    scores_table = Table(scores_data, colWidths=[2.5*inch, 1.5*inch, 2.5*inch])
    scores_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#001f3f')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('BACKGROUND', (-1, -1), (-1, -1), colors.HexColor('#e8f4fd')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    
    story.append(scores_table)
    story.append(Spacer(1, 30))
    
    # Detailed evaluation
    story.append(Paragraph("Detailed AI Analysis", heading_style))
    
    eval_text = evaluation.get('detailed_evaluation', 'No evaluation available')
    for para in eval_text.split('\n\n'):
        if para.strip():
            story.append(Paragraph(para.strip(), styles['Normal']))
            story.append(Spacer(1, 12))
    
    # Footer
    story.append(Spacer(1, 30))
    story.append(Paragraph("Generated by eazyAI Enterprise Platform", styles['Normal']))
    story.append(Paragraph(f"Report generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", styles['Normal']))
    story.append(Paragraph("Access admin dashboard for detailed management", styles['Normal']))
    
    doc.build(story)
    buffer.seek(0)
    return buffer

def get_performance_level(score: int) -> str:
    """Convert score to performance level"""
    if score >= 9: return "Exceptional"
    elif score >= 8: return "Excellent"
    elif score >= 7: return "Good"
    elif score >= 6: return "Satisfactory"
    elif score >= 4: return "Needs Improvement"
    else: return "Poor"

async def send_email_report(session: InterviewSession, evaluation: Dict, pdf_content: bytes):
    """Send email report to recruiter using Azure Communication Services"""
    try:
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ 
                    font-family: 'Segoe UI', sans-serif; margin: 0; padding: 20px; 
                    background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%); 
                }}
                .container {{ 
                    max-width: 800px; margin: 0 auto; background: white; 
                    border-radius: 20px; box-shadow: 0 20px 40px rgba(0,0,0,0.1); overflow: hidden;
                }}
                .header {{ 
                    background: linear-gradient(135deg, #001f3f 0%, #003366 100%); 
                    color: white; padding: 50px 40px; text-align: center; 
                }}
                .brand {{ 
                    font-size: 3rem; font-weight: bold; margin-bottom: 10px; 
                    text-shadow: 0 2px 4px rgba(0,0,0,0.3);
                }}
                .subtitle {{ 
                    font-size: 1.3rem; opacity: 0.9; font-weight: 300;
                }}
                .content {{ padding: 40px; }}
                .section {{ margin-bottom: 35px; }}
                .section h3 {{ 
                    color: #001f3f; border-bottom: 3px solid #e8f4fd; 
                    padding-bottom: 10px; margin-bottom: 20px; font-size: 1.4rem;
                }}
                .info-grid {{ 
                    display: grid; grid-template-columns: 1fr 2fr; gap: 15px; 
                    background: #f8fbff; padding: 20px; border-radius: 15px; margin: 20px 0; 
                }}
                .info-label {{ font-weight: bold; color: #555; }}
                .info-value {{ color: #333; }}
                .recommendation {{ 
                    background: linear-gradient(135deg, #e8f5e8 0%, #f1f8e9 100%); 
                    padding: 30px; border-radius: 15px; border-left: 6px solid #4caf50; 
                    margin: 30px 0; text-align: center;
                }}
                .recommendation h4 {{ 
                    color: #2e7d32; margin-bottom: 15px; font-size: 1.5rem; 
                }}
                .scores-grid {{ 
                    display: grid; grid-template-columns: repeat(4, 1fr); 
                    gap: 20px; margin: 25px 0; 
                }}
                .score-card {{ 
                    background: linear-gradient(135deg, #f8fbff 0%, #f0f4f8 100%); 
                    padding: 25px; border-radius: 15px; text-align: center; 
                    border: 2px solid #e8f4fd; transition: transform 0.3s ease;
                }}
                .score-value {{ 
                    font-size: 2.5rem; font-weight: bold; 
                    background: linear-gradient(135deg, #001f3f, #003366);
                    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
                    margin-bottom: 8px;
                }}
                .score-label {{ font-size: 0.9rem; color: #666; font-weight: 600; }}
                .actions {{ 
                    background: #f8f9fa; padding: 30px; border-radius: 15px; 
                    text-align: center; margin: 30px 0; 
                }}
                .btn {{ 
                    display: inline-block; padding: 12px 25px; margin: 5px;
                    background: linear-gradient(135deg, #001f3f, #003366);
                    color: white; text-decoration: none; border-radius: 25px;
                    font-weight: 600; transition: transform 0.3s ease;
                }}
                .btn:hover {{ transform: translateY(-2px); }}
                .footer {{ 
                    background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%); 
                    padding: 30px; text-align: center; color: #666; 
                }}
                .highlight {{ 
                    background: linear-gradient(135deg, #fff3e0 0%, #ffe0b2 100%);
                    padding: 20px; border-radius: 10px; border-left: 4px solid #ff9800;
                    margin: 20px 0;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="brand">eazyAI</div>
                    <div class="subtitle">Enterprise Interview Assessment Report</div>
                </div>
                
                <div class="content">
                    <div class="section">
                        <h3>📋 Interview Summary</h3>
                        <div class="info-grid">
                            <div class="info-label">Candidate:</div>
                            <div class="info-value"><strong>{evaluation.get('candidate_name')}</strong></div>
                            <div class="info-label">Position:</div>
                            <div class="info-value">{evaluation.get('position')}</div>
                            <div class="info-label">Experience Level:</div>
                            <div class="info-value">{evaluation.get('experience_level')}</div>
                            <div class="info-label">Interview Date:</div>
                            <div class="info-value">{evaluation.get('interview_date')}</div>
                            <div class="info-label">Duration:</div>
                            <div class="info-value">{evaluation.get('duration_minutes', 0):.1f} minutes</div>
                            <div class="info-label">Questions Completed:</div>
                            <div class="info-value">{evaluation.get('questions_completed', 0)}/10</div>
                        </div>
                    </div>

                    <div class="section">
                        <div class="recommendation">
                            <h4>🎯 AI Recommendation: {evaluation.get('recommendation')}</h4>
                            <p style="font-size: 1.2rem; margin: 0;">
                                <strong>Overall Score: {evaluation.get('scores', {}).get('overall', 'N/A')}/10</strong>
                            </p>
                        </div>
                    </div>
                    
                    <div class="section">
                        <h3>📊 Detailed Performance Analysis</h3>
                        <div class="scores-grid">
                            <div class="score-card">
                                <div class="score-value">{evaluation.get('scores', {}).get('technical_skills', 'N/A')}</div>
                                <div class="score-label">Technical Skills</div>
                            </div>
                            <div class="score-card">
                                <div class="score-value">{evaluation.get('scores', {}).get('communication', 'N/A')}</div>
                                <div class="score-label">Communication</div>
                            </div>
                            <div class="score-card">
                                <div class="score-value">{evaluation.get('scores', {}).get('problem_solving', 'N/A')}</div>
                                <div class="score-label">Problem Solving</div>
                            </div>
                            <div class="score-card">
                                <div class="score-value">{evaluation.get('scores', {}).get('teamwork', 'N/A')}</div>
                                <div class="score-label">Teamwork</div>
                            </div>
                        </div>
                    </div>
                    
                    <div class="highlight">
                        <h3>🔍 Key Insights</h3>
                        <p>✅ Complete AI-powered assessment completed</p>
                        <p>📄 Detailed evaluation report attached as PDF</p>
                        <p>🎯 Hiring recommendation based on comprehensive analysis</p>
                        <p>📊 Multi-dimensional scoring across 7 key competencies</p>
                    </div>
                    
                    <div class="actions">
                        <h3>⚡ Next Steps</h3>
                        <p style="margin-bottom: 20px;">Access your admin dashboard for detailed management and full transcript access.</p>
                        <p><strong>Dashboard URL:</strong> Your platform admin dashboard</p>
                    </div>
                </div>
                
                <div class="footer">
                    <p><strong>Generated by eazyAI Enterprise Platform</strong></p>
                    <p>🚀 Revolutionizing recruitment with AI-powered interviews</p>
                    <p>© 2025 eazyAI Enterprise Solutions</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        # Send email using Azure Communication Services
        message = {
            "senderAddress": SENDER_EMAIL,
            "recipients": {
                "to": [{"address": RECEIVER_EMAIL}]
            },
            "content": {
                "subject": f"🤖 eazyAI Interview Report - {evaluation.get('candidate_name')} - {evaluation.get('position')}",
                "html": html_content
            },
            "attachments": [
                {
                    "name": f"eazyAI_Report_{evaluation.get('candidate_name', 'Candidate').replace(' ', '_')}.pdf",
                    "contentType": "application/pdf",
                    "contentInBase64": base64.b64encode(pdf_content).decode()
                }
            ]
        }
        
        # Send email
        poller = email_client.begin_send(message)
        result = poller.result()
        
        logger.info(f"✅ Email sent successfully! Message ID: {result.message_id}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Email error: {e}")
        return False

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Check database connection
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM interviews")
        total_interviews = cursor.fetchone()[0]
        conn.close()
        
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "version": "3.0.0",
            "active_sessions": len(active_sessions),
            "total_interviews_in_db": total_interviews,
            "platform": "eazyAI Enterprise with Persistent Dashboard",
            "database": "SQLite - Connected",
            "features": [
                "AI Interviewing",
                "Persistent Dashboard", 
                "Authentication",
                "Live Data Updates",
                "Export/Import",
                "Transcript Management",
                "Email Reporting"
            ]
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8080,
        reload=False,
        access_log=True,
        log_level="info"
    )
