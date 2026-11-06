import os, uuid, subprocess, shutil
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

app = FastAPI(title="Myanmar Recap - Real Speech to Myanmar Subtitle")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
os.makedirs("uploads", exist_ok=True)
os.makedirs("outputs", exist_ok=True)

def translate_to_myanmar(text: str, src_lang: str = "auto"):
    """Translate any language -> Myanmar. Uses deep-translator Google."""
    if not text.strip():
        return text
    try:
        from deep_translator import GoogleTranslator
        # src auto detect
        return GoogleTranslator(source='auto', target='my').translate(text)
    except Exception as e:
        print("Translate fail, trying googletrans:", e)
        try:
            from googletrans import Translator
            return Translator().translate(text, dest='my').text
        except Exception as e2:
            print("Translate fail 2:", e2)
            return text  # fallback: original if translate fails

@app.get("/")
def home():
    return {"status": "Backend Running!", "message": "Real Speech -> Myanmar Subtitle Ready"}

@app.post("/api/upload")
async def upload_video(
    file: UploadFile = File(...),
    mode: str = Form("subtitle-only"), # subtitle-only | myanmar-voice
    voice: str = Form("ko-aung"),
    remove_bgm: bool = Form(True),
):
    job_id = str(uuid.uuid4())[:8]
    input_path = f"uploads/{job_id}_{file.filename}"
    with open(input_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # 1. WHISPER - Video�ဲက တကယ်ပြောနေတဲ့ စကားကို အချိန်နဲ့တကွ ထုတ်မယ်
    print(f"[{job_id}] Whisper transcribing...")
    import whisper
    model = whisper.load_model("base")  # tiny ထက် ပိုတိကျတယ်, base သုံးပါ
    result = model.transcribe(input_path, fp16=False, verbose=False)
    segments = result["segments"]  # [{start, end, text}]
    detected_lang = result.get("language", "en")
    print(f"Detected lang: {detected_lang}, segments: {len(segments)}")

    # 2. TRANSLATE EACH SEGMENT TO MYANMAR - အချိန်မပြောင်းဘဲ စာသားပဲ မြန်မာလို ပြောင်းမယ်
    myanmar_segments = []
    for seg in segments:
        original = seg["text"].strip()
        myanmar_text = translate_to_myanmar(original)
        myanmar_segments.append({
            "start": float(seg["start"]),
            "end": float(seg["end"]),
            "original": original,
            "text": myanmar_text,  # Myanmar translated - this is what will show as subtitle
            "myanmar": myanmar_text
        })
        print(f"{seg['start']:.1f}-{seg['end']:.1f} | {original} -> {myanmar_text}")

    # 3. CREATE .SRT with MYANMAR text + exact timing
    srt_path = f"outputs/{job_id}.srt"
    with open(srt_path, "w", encoding="utf-8") as s:
        for i, seg in enumerate(myanmar_segments, 1):
            def fmt(t):
                h=int(t//3600); m=int((t%3600)//60); sec=int(t%60); ms=int((t%1)*1000)
                return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"
            s.write(f"{i}\n{fmt(seg['start'])} --> {fmt(seg['end'])}\n{seg['text']}\n\n")

    # Also save JSON for frontend to show original vs Myanmar
    import json
    with open(f"outputs/{job_id}.json", "w", encoding="utf-8") as jf:
        json.dump({"detected_lang": detected_lang, "segments": myanmar_segments}, jf, ensure_ascii=False, indent=2)

    # 4. FFMPEG - Myanmar subtitle ကို Video ထဲမှာ အချိန်ကွက်တိ Burn-in လုပ်မယ်
    output_path = f"outputs/{job_id}_final.mp4"
    audio_filter = "highpass=f=200,volume=1.2" if remove_bgm else "volume=1.0"
    # Myanmar font needs Noto Myanmar - Render မှာ install လုပ်ထားရမယ်, fallback to default
    vf = f"scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,subtitles='{srt_path}':force_style='Fontsize=30,PrimaryColour=&H00FFFFFF,Outline=3,Shadow=2,Bold=1,MarginV=120'"
    cmd = ["ffmpeg","-y","-i",input_path,"-vf",vf,"-af",audio_filter,"-c:v","libx264","-preset","veryfast","-crf","23","-c:a","aac","-shortest",output_path]
    print("FFmpeg:", " ".join(cmd))
    subprocess.run(cmd, check=False)

    return {
        "job_id": job_id,
        "mode": mode,
        "voice": voice,
        "detected_language": detected_lang,
        "total_segments": len(myanmar_segments),
        "segments": myanmar_segments[:100],
        "download_url": f"/api/download/{job_id}",
        "download_link": f"download.myrecap.studio/{job_id}",
        "message": "Done! Real speech translated to Myanmar with exact timing"
    }

@app.get("/api/subtitle/{job_id}")
def get_subtitle(job_id: str):
    return FileResponse(f"outputs/{job_id}.srt", media_type="text/plain")

@app.get("/api/download/{job_id}")
def download(job_id: str):
    path = f"outputs/{job_id}_final.mp4"
    if not os.path.exists(path):
        return JSONResponse({"error": "Not found yet"}, status_code=404)
    return FileResponse(path, media_type="video/mp4", filename=f"recap_{job_id}_myanmar.mp4")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
