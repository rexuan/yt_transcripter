import re
import argparse
import requests
from youtube_transcript_api import (
    YouTubeTranscriptApi,
    TranscriptsDisabled,
    NoTranscriptFound,
)


# ==========================================================
# Utility Functions
# ==========================================================

def extract_video_id(url: str) -> str:
    patterns = [r"(?:v=|\/)([0-9A-Za-z_-]{11})"]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raise ValueError("Could not extract video ID from URL")


def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", name)


def get_video_title(video_id: str) -> str:
    url = f"https://www.youtube.com/watch?v={video_id}"
    response = requests.get(url)
    html = response.text

    match = re.search(r"<title>(.*?)</title>", html)
    if match:
        title = match.group(1).replace(" - YouTube", "").strip()
        return sanitize_filename(title)

    return video_id


def build_safe_filename(title: str, video_id: str, extension: str, cleaned=False):
    base = f"{title} ({video_id})"
    if cleaned:
        return f"{base}_cleaned.{extension}"
    return f"{base}.{extension}"


def format_timestamp_srt(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def format_timestamp_txt(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02}:{minutes:02}:{secs:02}"


def get_available_transcripts(video_id):
    try:
        transcript_list = YouTubeTranscriptApi().list(video_id)

        available = []

        for transcript in transcript_list:
            available.append({
                "language": transcript.language,
                "language_code": transcript.language_code,
                "is_generated": transcript.is_generated
            })

        return available

    except Exception as e:
        print(f"Error listing transcripts: {e}")
        return []


def fetch_smart_transcript(video_id):
    try:
        transcript_list = YouTubeTranscriptApi().list(video_id)

        # 1. Try any English variant
        for transcript in transcript_list:
            if "en" in transcript.language_code:
                return transcript.fetch()

        # 2. Try manual subtitles
        for transcript in transcript_list:
            if not transcript.is_generated:
                return transcript.fetch()

        # 3. Fallback to auto-generated
        for transcript in transcript_list:
            if transcript.is_generated:
                return transcript.fetch()

    except Exception as e:
        print(f"Error: {e}")

    return None


# ==========================================================
# Cleaning Logic
# ==========================================================

def clean_transcript_text(text: str) -> str:
    text = re.sub(r"\[.*?\]", "", text)
    text = re.sub(r"\b(uh|um|erm|ah|like)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(\w+)\s+\1\b", r"\1", text, flags=re.IGNORECASE)
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    text = text.strip()

    if text:
        text = text[0].upper() + text[1:]

    return text


# ==========================================================
# Transcript Fetching
# ==========================================================

def fetch_transcript(video_id: str, languages: list):
    try:
        return YouTubeTranscriptApi().fetch(video_id, languages=languages)
    except NoTranscriptFound:
        print(f"No transcript found for languages: {languages}")
    except TranscriptsDisabled:
        print("Transcripts are disabled for this video.")
    except Exception as e:
        print(f"Error fetching transcript: {e}")
    return None


# ==========================================================
# Formatting Output
# ==========================================================

def format_as_txt(transcript, keep_timestamps: bool) -> str:
    lines = []

    for item in transcript:
        if keep_timestamps:
            ts = format_timestamp_txt(item.start)
            lines.append(f"[{ts}] {item.text}")
        else:
            lines.append(item.text)

    return "\n".join(lines)


def format_as_srt(transcript) -> str:
    srt_lines = []

    for i, item in enumerate(transcript, start=1):
        start = format_timestamp_srt(item.start)
        end = format_timestamp_srt(item.start + item.duration)

        srt_lines.append(str(i))
        srt_lines.append(f"{start} --> {end}")
        srt_lines.append(item.text)
        srt_lines.append("")

    return "\n".join(srt_lines)


# ==========================================================
# Main CLI
# ==========================================================

def main():
    parser = argparse.ArgumentParser(
        description="Extract and process YouTube video transcripts.",
        epilog="""
Examples:

  Basic:
    python %(prog)s "URL"

  Save TXT:
    python %(prog)s "URL" --save

  Export SRT:
    python %(prog)s "URL" --format srt --save

  Language fallback:
    python %(prog)s "URL" --lang en,ms

  Clean mode:
    python %(prog)s "URL" --save --clean
        
Arguments (i.e., URL) and optional switches may be specified in any order.

When output cleaned transcript is placed after original transcript which will be end of the file,
to allow scroll after EOF,
Methods:
    1. Unix command to physically append fake blank lines at the bottom before piping into less
    (python %(prog)s "URL" ;yes ""| head -n 300) | less
    Where 300 is the number of blank new lines being added, can be modified to any number large enough
    ?2. less -z-300 
    where -z option controls the scroll window size
""",
    formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument("url", help="YouTube video URL")

    parser.add_argument(
        "--timestamps",
        action="store_true",
        help="Include timestamps (TXT only)"
    )

    parser.add_argument(
        "--save",
        action="store_true",
        help="Save transcript to file using safe filename (title + video_id)"
    )

    parser.add_argument(
        "--lang",
        type=str,
        default="en",
        help="Comma-separated language codes (fallback order)"
    )

    parser.add_argument(
        "--format",
        type=str,
        default="txt",
        choices=["txt", "srt"],
        help="Output format (default: txt)"
    )

    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean transcript (remove fillers, noise, repeated words, merge lines)"
    )

    args = parser.parse_args()

    try:
        video_id = extract_video_id(args.url)
    except ValueError as e:
        print(e)
        return
        
    available = get_available_transcripts(video_id)

    print("Available subtitles:")
    for t in available:
        print(f"- {t['language']} ({t['language_code']}) | Auto: {t['is_generated']}")

    languages = [lang.strip() for lang in args.lang.split(",")]
    
    print(f"Fetching transcript for video: {video_id}")
    #print(f"Language fallback order: {languages}")
    #transcript = fetch_transcript(video_id, languages)
    transcript = fetch_smart_transcript(video_id)

    if not transcript:
        print("No subtitles/transcript available.")
        return

    if args.format == "txt":
        output_text = format_as_txt(transcript, args.timestamps)
        extension = "txt"
    else:
        output_text = format_as_srt(transcript)
        extension = "srt"

    cleaned_text = None
    if args.clean and args.format == "txt":
        cleaned_text = clean_transcript_text(output_text)

    if args.save:
        title = get_video_title(video_id)

        original_filename = build_safe_filename(title, video_id, extension)
        with open(original_filename, "w", encoding="utf-8") as f:
            f.write(output_text)
        print(f"Saved original to: {original_filename}")

        if cleaned_text:
            cleaned_filename = build_safe_filename(title, video_id, "txt", cleaned=True)
            with open(cleaned_filename, "w", encoding="utf-8") as f:
                f.write(cleaned_text)
            print(f"Saved cleaned version to: {cleaned_filename}")

    else:
        if cleaned_text:
            print("\n===== CLEANED TRANSCRIPT =====\n")
            print(cleaned_text)
            
        print("\n===== ORIGINAL TRANSCRIPT =====\n")
        print(output_text)


if __name__ == "__main__":
    main()


# ==========================================================
# TODO (Future Enhancements)
# ==========================================================

# - Add JSON export format (--format json)
# - Add Markdown export format (--format md)
# - Add manual vs auto caption selection (--manual-only / --auto-only)
# - Add batch URL processing (--file urls.txt)
# - Add output directory option (--output ./folder)
# - Add AI-based grammar polishing (--ai-clean)
# - Add verbose / quiet logging modes (--verbose / --quiet)
# - Add rate limiting for batch processing
# - Add auto-translate transcript (--translate <lang>)
