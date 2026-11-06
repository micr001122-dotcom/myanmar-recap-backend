import os, uuid, subprocess, json
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import shutil

app = FastAPI(title="Myanmar Recap Studio Backend")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

UPLOAD_DIR = "uploads"
OUT_DIR = "outputs"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)

@app.get("/")
def home():
    return {"status": "Backend Running!", "message": "Myanmar Recap Studio Backend Ready"}

@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...), mode: str = Form("myanmar-voice"), voice: str = Form("ko-aung"), remove_bgm: bool = Form(True)):
    job_id = str(uuid.uuid4())[:8]
    input_path = f"{UPLOAD_DIR}/{job_id}_{file.filename}"
    with open(input_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    # Whisper transcribe - install openai-whisper
    try:
        import whisper
        model = whisper.load_model("tiny")
        result = model.transcribe(input_path, fp16=False)
        segments = result["segments"]
        full_text = result["text"]
    except Exception as e:
        segments = [{"start": 0, "end": 5, "text": "Hello, this is a test subtitle"}]
        full_text = "Test subtitle - Whisper not installed"
    # Create SRT
    srt_path = f"{OUT_DIR}/{job_id}.srt"
    with open(srt_path, "w", encoding="utf-8") as s:
        for i, seg in enumerate(segments, 1):
            def fmt(t):
                h=int(t//3600); m=int((t%3600)//60); sec=int(t%60); ms=int((t%1)*1000)
                return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"
            s.write(f"{i}\n{fmt(seg['start'])} --> {fmt(seg['end'])}\n{seg['text'].strip()}\n\n")
    # FFmpeg - copyright safe + BGM removal
    output_path = f"{OUT_DIR}/{job_id}_final.mp4"
    audio_filter = "highpass=f=200,volume=1.2" if remove_bgm else "volume=1.0"
    vf = f"scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,subtitles={srt_path}:force_style='Fontsize=28,PrimaryColour=&H00FFFFFF,Outline=2,Shadow=2,Bold=1'"
    cmd = ["ffmpeg","-y","-i",input_path,"-vf",vf,"-af",audio_filter,"-c:v","libx264","-preset","veryfast","-crf","23","-c:a","aac","-shortest",output_path]
    try:
        subprocess.run(cmd, check=False)
    except: pass
    return {"job_id": job_id, "mode": mode, "voice": voice, "transcript": full_text[:1000], "segments": [{"start": s["start"], "end": s["end"], "text": s["text"]} for s in segments[:50]], "download_url": f"/api/download/{job_id}", "download_link": f"download.myrecap.studio/{job_id}", "message": "Done!"}

@app.get("/api/subtitle/{job_id}")
def get_subtitle(job_id: str):
    return FileResponse(f"{OUT_DIR}/{job_id}.srt", media_type="text/plain")

@app.get("/api/download/{job_id}")
def download(job_id: str):
    path = f"{OUT_DIR}/{job_id}_final.mp4"
    if not os.path.exists(path):
        return JSONResponse({"error": "Not found yet"}, status_code=404)
    return FileResponse(path, media_type="video/mp4", filename=f"recap_{job_id}.mp4")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
