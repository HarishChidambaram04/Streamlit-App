
from fastapi import FastAPI, File, UploadFile, HTTPException, Form,Request,Response
from fastapi.responses import StreamingResponse
from fastapi.responses import JSONResponse
import cv2
import pytesseract
import re
import os
import pandas as pd
import datetime
from datetime import datetime, timedelta
import tempfile
import subprocess
from pydantic import BaseModel
from pathlib import Path
import requests
from bs4 import BeautifulSoup
from io import StringIO
import csv

app = FastAPI()

# Setup Tesseract OCR path
pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'



UPLOAD_DIR = tempfile.gettempdir()
time_storage={}


DOCUMENTS_DIR = Path.home() / "Documents/TrimmedVideos"
DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)  # Ensure the folder exists


ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}

def is_valid_video_file(filename: str) -> bool:
    """Check if the uploaded file is a valid video format."""
    return any(filename.lower().endswith(ext) for ext in ALLOWED_EXTENSIONS)

# Extract timestamp from video frame (customizable region)
def extract_timestamp(frame, x=0, y=0, w=950, h=60):
    try:
        timestamp_crop = frame[y:y+h, x:x+w]
        timestamp_grey = cv2.cvtColor(timestamp_crop, cv2.COLOR_BGR2GRAY)
        _, timestamp_thresh = cv2.threshold(timestamp_grey, 127, 255, cv2.THRESH_BINARY)
        candidate_str = pytesseract.image_to_string(timestamp_thresh, config='--psm 6')
        regex_str = r'(?i)Date:\s*(\d{4}-\d{2}-\d{2})\s*Time:\s*(\d{1,2}:\d{2}:\d{2}\s*(?:AM|PM))'
        match = re.search(regex_str, candidate_str)
        if match:
            return match.groups()
    except Exception as e:
        return None, None
    return None, None

# Get timestamp from a specific video frame
def get_video_timestamp(video_path, frame_position):
    cap = cv2.VideoCapture(video_path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_position)
    ret, frame = cap.read()
    cap.release()
    if ret:
        return extract_timestamp(frame)
    return None, None

# Extract the initial timestamp from the video
def get_initial_time(video_path):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return "00:00:00 AM"
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    for i in range(0, min(100, frame_count)):
        _, time_str = get_video_timestamp(video_path, i)
        if time_str:
            cap.release()
            return time_str
    cap.release()
    return "00:00:00 AM"

# Extract the final timestamp from the video
def get_video_end_time(video_path):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return "00:00:00 AM"
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    for i in range(frame_count - 1, max(0, frame_count - 100) - 1, -1):
        _, time_str = get_video_timestamp(video_path, i)
        if time_str:
            cap.release()
            return time_str
    cap.release()
    return "00:00:00 AM"

# Convert time string to seconds for easier manipulation
def time_to_seconds(time_str):
    try:
        time_obj = datetime.strptime(time_str, '%I:%M:%S %p')
        return time_obj.hour * 3600 + time_obj.minute * 60 + time_obj.second
    except ValueError:
        return 0




def parse_data(raw_text):
    field_patterns = {
        "Registration Number": r"REGISTRATION NUMBER\s*:\s*(\d+)",
        "Full Name": r"FULL NAME\s*:\s*([A-Za-z\s]+)",
        "Mobile": r"MOBILE\s*:\s*(\d{10})",
        "Company": r"COMPANY\s*:\s*([\w\s&.,-]+)",
        "Designation": r"DESIGNATION\s*:\s*([\w\s&.,-]+)",
        "Address": r"ADDRESS\s*:\s*([\w\s&.,-]+)",
        "City": r"CITY\s*:\s*([\w\s]+)",
        "State": r"STATE\s*:\s*([\w\s]+)",
        "Pincode": r"PINCODE\s*:\s*(\d{6})",
        "Email": r"EMAIL\s*:\s*([\w.\-]+@[\w.\-]+\.\w+)",
    }
    parsed_data = {}
    for field, pattern in field_patterns.items():
        match = re.search(pattern, raw_text, re.IGNORECASE)
        value = match.group(1).strip() if match else ""
        value = re.sub(r'\b(MOBILE|DESIGNATION|ADDRESS|CITY|STATE|PINCODE)\b', '', value, flags=re.IGNORECASE).strip()
        parsed_data[field] = value
    return parsed_data if parsed_data.get("Registration Number") else None

def process_urls(excel_data):
    fieldnames = ["Registration Number", "Full Name", "Mobile", "Company", "Designation",
                  "Address", "City", "State", "Pincode", "Email", "Date", "Time"]
    seen_entries = set()
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for _, row in excel_data.iterrows():
        url, date, time = row["Data"], row.get("Date", ""), row.get("Time", "")
        if not url.startswith("https://www.smartexpos.in/vr/pass/"):
            continue  # Skip invalid URLs

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://www.smartexpos.in/",
            "Connection": "keep-alive"
        }

        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
        except requests.RequestException:
            continue  # Skip network errors

        soup = BeautifulSoup(response.content, "html.parser")
        table = soup.find('table')
        if not table:
            continue  # Skip if no data found

        raw_text = table.get_text(" ", strip=True)
        parsed_data = parse_data(raw_text)
        if not parsed_data:
            continue  # Skip if parsing fails

        entry_id = f"{parsed_data['Registration Number']}|{parsed_data['Full Name']}"
        if entry_id not in seen_entries:
            seen_entries.add(entry_id)
            parsed_data.update({"Date": date, "Time": time})
            writer.writerow(parsed_data)

    output.seek(0)
    return output

@app.post("/process/")
async def process_file(file: UploadFile = File(...)):
    file_extension = file.filename.split('.')[-1].lower()
    if file_extension not in ["csv", "xlsx"]:
        raise HTTPException(status_code=400, detail="Invalid file format")

    try:
        file.file.seek(0)  # Ensure file pointer is at the beginning
        df = pd.read_csv(file.file) if file_extension == "csv" else pd.read_excel(file.file, engine='openpyxl')
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading file: {str(e)}")

    if "Data" not in df.columns:
        raise HTTPException(status_code=400, detail="Column 'Data' not found in file")

    output_csv = process_urls(df)

    return StreamingResponse(output_csv, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=processed_data.csv"})


@app.post("/upload_video/")
def upload_video(file: UploadFile = File(...)):
    try:
        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(temp_dir, file.filename)
        with open(file_path, "wb") as buffer:
            buffer.write(file.file.read())
        
        initial_time = get_initial_time(file_path)
        end_time = get_video_end_time(file_path)
        
        return JSONResponse(content={"file_path": file_path, "initial_time": initial_time, "end_time": end_time})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/upload_csv/")
async def upload_csv(file: UploadFile):
    csv_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(csv_path, "wb") as f:
        f.write(file.file.read())
    df = pd.read_csv(csv_path, dtype=str)
    return JSONResponse({"file_path": csv_path, "columns": list(df.columns)})



@app.post("/filter_csv/")
async def filter_csv(file_path: str = Form(...), column: str = Form(...), value: str = Form(...)):
    df = pd.read_csv(file_path, dtype=str)
    filtered_df = df[df[column] == value]
    return JSONResponse({"filtered_data": filtered_df.to_dict(orient="records")})




@app.post("/jump_to_time/")
async def jump_to_time(initial_time: str = Form(...), jump_time: str = Form(...)):
    """Calculate jump time in seconds."""
    try:
        jump_seconds = time_to_seconds(jump_time) - time_to_seconds(initial_time)

        if jump_seconds < 0:
            return JSONResponse({"error": "Jump time cannot be before initial time"}, status_code=400)

        return JSONResponse({"jump_seconds": jump_seconds})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/trim_video/")
async def trim_video(
    file_path: str = Form(...), 
    start_time: str = Form(...), 
    end_time: str = Form(...), 
    initial_time_str: str = Form(...)
):
    """Trim video using FFmpeg and return new file path."""
    video_path = Path(file_path)

    if not video_path.exists():
        return JSONResponse({"error": "File not found"}, status_code=404)

    initial_time_sec = time_to_seconds(initial_time_str)
    start_time_sec = time_to_seconds(start_time) - initial_time_sec
    end_time_sec = time_to_seconds(end_time) - initial_time_sec

    if start_time_sec < 0 or end_time_sec < 0 or start_time_sec >= end_time_sec:
        return JSONResponse({"error": "Invalid start or end time"}, status_code=400)

    # Define trimmed file save location
    trimmed_filename = video_path.stem + "_trimmed.mp4"
    trimmed_file_path = DOCUMENTS_DIR / trimmed_filename

    ffmpeg_command = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",  # Suppress logs for speed
        "-i", str(video_path),
        "-ss", str(start_time_sec),
        "-to", str(end_time_sec),
        "-c:v", "libx264", "-preset", "ultrafast",  # 🚀 Fastest encoding
        "-c:a", "aac", "-strict", "experimental",
        str(trimmed_file_path)
    ]

    try:
        subprocess.run(ffmpeg_command, check=True)
        return JSONResponse({"trimmed_video_path": str(trimmed_file_path)})
    except subprocess.CalledProcessError as e:
        return JSONResponse({"error": f"FFmpeg Error: {e}"}, status_code=500)




















































































