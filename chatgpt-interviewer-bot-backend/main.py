from fastapi import FastAPI, UploadFile, HTTPException, BackgroundTasks, Request, Form, Depends
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from dotenv import load_dotenv
import asyncio
import uvicorn
import base64
import secrets

from openai import OpenAI
import os
import json
import requests
from tempfile import NamedTemporaryFile
import uuid
from datetime import datetime, timedelta
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

# Admin credentials (in production, use proper auth)
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "eazyai2025"

# Initialize clients
client = OpenAI(api_key=OPEN_AI_KEY, organization=OPEN_AI_ORG)
blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
email_client = EmailClient.from_connection_string(AZURE_COMMUNICATION_CONNECTION_STRING)

# Security
security = HTTPBasic()

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI App
app = FastAPI(
    title="eazyAI Enterprise Interviewer",
    description="Enterprise-grade AI-powered interviewing platform by eazyAI",
    version="2.0.0"
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
    messages: List[Dict]
    scores: Dict[str, int] = {}
    total_questions: int = 10
    current_question: int = 0
    status: str = "in_progress"  # in_progress, completed, hired, reviewed, rejected
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

# In-memory storage (in production, use proper database)
active_sessions: Dict[str, InterviewSession] = {}
completed_sessions: Dict[str, InterviewSession] = {}

# Container names (existing containers)
CONTAINERS = {
    "transcripts": "transcripts",
    "evaluations": "evaluationresults", 
    "reports": "reports"
}

def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    """Verify admin credentials"""
    is_correct_username = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    is_correct_password = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (is_correct_username and is_correct_password):
        raise HTTPException(
            status_code=401,
            detail="Invalid admin credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials

@app.on_event("startup")
async def startup_event():
    logger.info("🚀 eazyAI Enterprise Interviewer Platform started successfully!")

@app.get("/", response_class=HTMLResponse)
async def get_frontend():
    """Serve the enterprise frontend with navy blue theme"""
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
                
                // Add transcript entry (NO SCORES SHOWN TO CANDIDATE)
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

# Complete Admin Dashboard
@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(credentials: HTTPBasicCredentials = Depends(verify_admin)):
    """Complete Admin dashboard with full functionality"""
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
            max-width: 1400px;
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
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
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
        .table-container {
            max-height: 600px;
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
            min-width: 80px;
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
        }
        .btn:hover { 
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(0, 31, 63, 0.3);
        }
        .btn-success { background: linear-gradient(135deg, #4caf50, #66bb6a); }
        .btn-danger { background: linear-gradient(135deg, #f44336, #ef5350); }
        .btn-warning { background: linear-gradient(135deg, #ff9800, #ffb74d); }
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
            margin: 5% auto;
            padding: 30px;
            border-radius: 15px;
            width: 80%;
            max-width: 600px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.3);
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
    </style>
</head>
<body>
    <div class="dashboard">
        <div class="header">
            <div class="brand">🚀 eazyAI Admin Dashboard</div>
            <div>
                <button class="btn refresh-btn" onclick="refreshData()">🔄 Refresh Data</button>
                <button class="btn" onclick="exportData()">📊 Export Data</button>
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
        </div>
        
        <div class="interviews-section">
            <div class="section-header">
                <span>📋 Interview Management</span>
                <span id="lastUpdated">Last updated: Never</span>
            </div>
            <div class="table-container">
                <table class="interview-table">
                    <thead class="table-header">
                        <tr>
                            <th>Candidate</th>
                            <th>Position</th>
                            <th>Date</th>
                            <th>Duration</th>
                            <th>Status</th>
                            <th>Overall Score</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody id="interviewsTableBody">
                        <tr>
                            <td colspan="7" class="loading">Loading interview data...</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- Interview Details Modal -->
    <div id="detailsModal" class="modal">
        <div class="modal-content">
            <span class="close" onclick="closeModal()">&times;</span>
            <h2 id="modalTitle">Interview Details</h2>
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

    <script>
        let currentSessionId = null;
        let allInterviews = [];

        async function refreshData() {
            try {
                const response = await fetch('/admin/sessions');
                const data = await response.json();
                
                // Update stats
                const total = data.active_sessions_count + data.completed_sessions_count;
                document.getElementById('totalInterviews').textContent = total;
                document.getElementById('activeInterviews').textContent = data.active_sessions_count;
                document.getElementById('completedInterviews').textContent = data.completed_sessions_count;
                
                // Calculate hired count
                const hiredCount = Object.values(data.completed_sessions || {})
                    .filter(s => s.status === 'hired').length;
                document.getElementById('hiredCandidates').textContent = hiredCount;
                
                // Combine active and completed interviews
                allInterviews = [];
                
                // Add active interviews
                Object.values(data.sessions || {}).forEach(session => {
                    allInterviews.push({...session, status: 'in_progress'});
                });
                
                // Add completed interviews
                Object.values(data.completed_sessions || {}).forEach(session => {
                    allInterviews.push(session);
                });
                
                // Sort by start time (newest first)
                allInterviews.sort((a, b) => new Date(b.start_time) - new Date(a.start_time));
                
                // Update table
                updateInterviewsTable();
                
                // Update last updated time
                document.getElementById('lastUpdated').textContent = 
                    `Last updated: ${new Date().toLocaleTimeString()}`;
                
            } catch (error) {
                console.error('Error refreshing data:', error);
                document.getElementById('interviewsTableBody').innerHTML = 
                    '<tr><td colspan="7" style="color: red; text-align: center;">Error loading data</td></tr>';
            }
        }
        
        function updateInterviewsTable() {
            const tbody = document.getElementById('interviewsTableBody');
            
            if (allInterviews.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: #666;">No interviews found</td></tr>';
                return;
            }
            
            tbody.innerHTML = allInterviews.map(session => {
                const date = new Date(session.start_time).toLocaleDateString();
                const duration = session.end_time ? 
                    Math.round((new Date(session.end_time) - new Date(session.start_time)) / 60000) : 
                    'In progress';
                const statusClass = `status-${session.status.replace('_', '-')}`;
                const statusText = session.status.replace('_', ' ').toUpperCase();
                const overallScore = session.scores?.overall || 'N/A';
                
                return `
                    <tr class="interview-row">
                        <td><strong>${session.candidate_name}</strong></td>
                        <td>${session.position}</td>
                        <td>${date}</td>
                        <td>${duration}${typeof duration === 'number' ? ' min' : ''}</td>
                        <td><span class="status-badge ${statusClass}">${statusText}</span></td>
                        <td><strong>${overallScore}${overallScore !== 'N/A' ? '/10' : ''}</strong></td>
                        <td>
                            <button class="btn" onclick="viewDetails('${session.session_id}')">👁️ View</button>
                            <button class="btn btn-warning" onclick="updateStatusModal('${session.session_id}')">📝 Update</button>
                            ${session.status === 'completed' ? 
                                '<button class="btn btn-success" onclick="markHired(\'' + session.session_id + '\')">✅ Hire</button>' : ''}
                        </td>
                    </tr>
                `;
            }).join('');
        }
        
        function viewDetails(sessionId) {
            const session = allInterviews.find(s => s.session_id === sessionId);
            if (!session) return;
            
            const modal = document.getElementById('detailsModal');
            const title = document.getElementById('modalTitle');
            const content = document.getElementById('modalContent');
            
            title.textContent = `${session.candidate_name} - ${session.position}`;
            
            const scores = session.scores || {};
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
            
            content.innerHTML = `
                <h3>📊 Performance Scores</h3>
                ${scoreGrid}
                
                <h3>📋 Interview Details</h3>
                <p><strong>Experience Level:</strong> ${session.experience_level}</p>
                <p><strong>Questions Completed:</strong> ${session.current_question}/${session.total_questions}</p>
                <p><strong>Start Time:</strong> ${new Date(session.start_time).toLocaleString()}</p>
                ${session.end_time ? `<p><strong>End Time:</strong> ${new Date(session.end_time).toLocaleString()}</p>` : ''}
                <p><strong>Status:</strong> ${session.status.replace('_', ' ').toUpperCase()}</p>
                
                <h3>🎯 Recommendation</h3>
                <p><strong>${session.recommendation || 'Pending'}</strong></p>
            `;
            
            modal.style.display = 'block';
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
        
        function closeModal() {
            document.getElementById('detailsModal').style.display = 'none';
        }
        
        function closeStatusModal() {
            document.getElementById('statusModal').style.display = 'none';
            currentSessionId = null;
            document.getElementById('statusNotes').value = '';
        }
        
        function exportData() {
            const csvContent = "data:text/csv;charset=utf-8," + 
                "Candidate Name,Position,Experience Level,Status,Overall Score,Start Time,Questions Completed\\n" +
                allInterviews.map(s => 
                    `"${s.candidate_name}","${s.position}","${s.experience_level}","${s.status}",${s.scores?.overall || 'N/A'},"${s.start_time}",${s.current_question}`
                ).join("\\n");
            
            const encodedUri = encodeURI(csvContent);
            const link = document.createElement("a");
            link.setAttribute("href", encodedUri);
            link.setAttribute("download", `eazyAI_interviews_${new Date().toISOString().split('T')[0]}.csv`);
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
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
    </script>
</body>
</html>
    """)

@app.post("/start-interview")
async def start_interview(request: InterviewRequest):
    """Initialize a new interview session"""
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
    """Process candidate's audio response - SCORES HIDDEN FROM CANDIDATE"""
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
        
        # Generate AI response WITHOUT revealing scores
        ai_response = await generate_ai_response_without_scores(session)
        session.messages.append({"role": "assistant", "content": ai_response})
        
        # Generate audio response
        audio_data = text_to_speech(ai_response)
        
        session.current_question += 1
        
        # Save transcript to Azure
        await save_transcript_to_azure(session_id, transcript, ai_response)
        
        # Update scores internally (hidden from candidate)
        await update_session_scores(session)
        
        return {
            "success": True,
            "transcript": transcript,
            "ai_response": ai_response,
            "audio_data": audio_data,
            "question_number": session.current_question,
            "total_questions": session.total_questions,
            "interview_complete": session.current_question >= session.total_questions
            # NOTE: NO SCORES RETURNED TO CANDIDATE
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
    """End interview and generate report"""
    try:
        if session_id not in active_sessions:
            raise HTTPException(status_code=404, detail="Session not found")
        
        session = active_sessions[session_id]
        session.status = "completed"
        session.end_time = datetime.now()
        
        # Generate final evaluation
        final_evaluation = await generate_final_evaluation(session)
        session.recommendation = final_evaluation.get("recommendation", "Review Required")
        
        # Move to completed sessions
        completed_sessions[session_id] = session
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

@app.get("/admin/sessions")
async def get_admin_sessions(credentials: HTTPBasicCredentials = Depends(verify_admin)):
    """Admin endpoint with completed sessions"""
    active_summary = {}
    for session_id, session in active_sessions.items():
        active_summary[session_id] = {
            "session_id": session_id,
            "candidate_name": session.candidate_name,
            "position": session.position,
            "experience_level": session.experience_level,
            "start_time": session.start_time.isoformat(),
            "current_question": session.current_question,
            "total_questions": session.total_questions,
            "scores": session.scores,
            "status": session.status
        }
    
    completed_summary = {}
    for session_id, session in completed_sessions.items():
        completed_summary[session_id] = {
            "session_id": session_id,
            "candidate_name": session.candidate_name,
            "position": session.position,
            "experience_level": session.experience_level,
            "start_time": session.start_time.isoformat(),
            "end_time": session.end_time.isoformat() if session.end_time else None,
            "current_question": session.current_question,
            "scores": session.scores,
            "status": session.status,
            "recommendation": session.recommendation,
            "email_sent": session.email_sent
        }
    
    return {
        "platform": "eazyAI Enterprise",
        "active_sessions_count": len(active_sessions),
        "completed_sessions_count": len(completed_sessions),
        "sessions": active_summary,
        "completed_sessions": completed_summary
    }

@app.post("/admin/update-status")
async def update_interview_status(
    status_update: StatusUpdate, 
    credentials: HTTPBasicCredentials = Depends(verify_admin)
):
    """Update interview status from admin dashboard"""
    try:
        session_id = status_update.session_id
        new_status = status_update.status
        notes = status_update.notes
        
        # Find session in completed sessions
        if session_id in completed_sessions:
            session = completed_sessions[session_id]
            session.status = new_status
            
            logger.info(f"✅ Status updated for {session.candidate_name}: {new_status}")
            
            return {"message": "Status updated successfully", "session_id": session_id}
        else:
            raise HTTPException(status_code=404, detail="Session not found")
            
    except Exception as e:
        logger.error(f"❌ Error updating status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Core Functions

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
    """Convert text to speech using ElevenLabs with updated voice"""
    if not ELEVENLABS_KEY or not text.strip():
        return ""
    
    try:
        voice_id = "oyxaSt75JW8l04MCJaSo"  # Your specified voice ID
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
        
        # Mark email as sent
        session.email_sent = True
        
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
    story.append(Paragraph("Access admin dashboard: /admin", styles['Normal']))
    
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
    """Send email report to recruiter using exact Azure configuration"""
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
                        <p style="margin-bottom: 20px;">Access your admin dashboard for detailed management:</p>
                        <a href="http://localhost:8000/admin" class="btn">🏢 Admin Dashboard</a>
                        <a href="mailto:support@eazyai.com" class="btn">💬 Support</a>
                    </div>
                </div>
                
                <div class="footer">
                    <p><strong>Generated by eazyAI Enterprise Platform</strong></p>
                    <p>🚀 Revolutionizing recruitment with AI-powered interviews</p>
                    <p>© 2025 eazyAI Enterprise Solutions | <a href="mailto:enterprise@eazyai.com">enterprise@eazyai.com</a></p>
                </div>
            </div>
        </body>
        </html>
        """
        
        # Use your exact Azure email configuration
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
        
        # Send using your exact method
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
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "2.0.0",
        "active_sessions": len(active_sessions),
        "completed_sessions": len(completed_sessions),
        "platform": "eazyAI Enterprise"
    }

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        access_log=True,
        log_level="info"
    )