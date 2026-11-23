import os, time, threading, subprocess
from flask import Flask
import pytchat
from supabase import create_client
from google import genai

app = Flask(__name__)

VIDEO_ID = os.environ["YOUTUBE_VIDEO_ID"]
supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
ai = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

def process_clip(video_id, hype_score, chat_sample):
    ts = int(time.time())
    filename = f"clip_{ts}.mp4"
    stream_url = f"https://www.youtube.com/watch?v={video_id}"

    cmd = f'yt-dlp -f "best[height<=720]" -g "{stream_url}"'
    direct_url = subprocess.check_output(cmd, shell=True).decode().strip()
    subprocess.run([
        "ffmpeg", "-y", "-sseof", "-25", "-i", direct_url,
        "-t", "20", "-c:v", "libx264", "-preset", "ultrafast", filename
    ], check=True)

    prompt = f"Write a short, punchy 6-word viral clip title based on this live chat reaction: {chat_sample[:500]}"
    title = ai.models.generate_content(model="gemini-2.5-flash", contents=prompt).text.strip()

    with open(filename, "rb") as f:
        supabase.storage.from_("stream-clips").upload(
            path=filename,
            file=f,
            file_options={"content-type": "video/mp4", "upsert": "true"}
        )

    public_url = supabase.storage.from_("stream-clips").get_public_url(filename)
    os.remove(filename)

    supabase.table("clips").insert({
        "title": title,
        "video_url": public_url,
        "hype_score": hype_score
    }).execute()

def monitor_stream():
    while True:
        try:
            chat = pytchat.create(video_id=VIDEO_ID)
            msg_buffer = []
            window_start = time.time()

            while chat.is_alive():
                for c in chat.get().sync_items():
                    msg_buffer.append(c.message)

                if time.time() - window_start >= 10:
                    msg_count = len(msg_buffer)
                    if msg_count > 120:
                        hype_score = min(100, int((msg_count / 300) * 100))
                        process_clip(VIDEO_ID, hype_score, " | ".join(msg_buffer[-30:]))
                        time.sleep(30)
                    msg_buffer = []
                    window_start = time.time()
                time.sleep(1)
        except Exception as e:
            print("Stream offline or error:", e)
            time.sleep(60)

@app.route("/")
def health():
    return "Clipper worker is alive!"

if __name__ == "__main__":
    threading.Thread(target=monitor_stream, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
