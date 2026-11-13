import time
import difflib
import cv2
import mss
import numpy as np
import easyocr
import gspread
from google import genai

# ==========================================
# CONFIGURATION
# ==========================================
SPREADSHEET_ID = "YOUR_GOOGLE_SHEET_ID_HERE"
CREDENTIALS_FILE = "service_account.json"
SHEET_TAB_NAME = "Sheet1"

# Screen bounding boxes (Adjust these pixel coordinates to match your game window!)
# Format: {"top": y, "left": x, "width": w, "height": h}
QUESTION_REGION = {"top": 400, "left": 600, "width": 720, "height": 150}
PLAYERS_REGION  = {"top": 200, "left": 200, "width": 1520, "height": 700}

# Similarity threshold (0.0 to 1.0) to prevent logging duplicate OCR reads
SIMILARITY_THRESHOLD = 0.80 
SCAN_INTERVAL_SEC = 1.5

# ==========================================
# INITIALIZATION
# ==========================================
print("Initializing OCR engine (this may take a moment on first run)...")
reader = easyocr.Reader(['en'], gpu=True) # Set gpu=False if you don't have an NVIDIA GPU

print("Connecting to Google Sheets...")
gc = gspread.service_account(filename=CREDENTIALS_FILE)
worksheet = gc.open_by_key(SPREADSHEET_ID).worksheet(SHEET_TAB_NAME)

print("Connecting to Gemini AI...")
ai_client = genai.Client()

# ==========================================
# HELPER FUNCTIONS
# ==========================================
def is_similar(text1: str, text2: str, threshold: float = SIMILARITY_THRESHOLD) -> bool:
    """Checks if two OCR strings are basically the same (ignores minor OCR typos)."""
    return difflib.SequenceMatcher(None, text1.lower(), text2.lower()).ratio() >= threshold

def capture_and_read(sct, region: dict, is_question: bool = False) -> list[str]:
    """Captures a screen region and returns detected text strings."""
    screenshot = sct.grab(region)
    img = np.array(screenshot)
    # Convert BGRA to Grayscale for cleaner OCR
    gray = cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
    
    # Run OCR
    results = reader.readtext(gray, detail=0)
    cleaned = [text.strip() for text in results if len(text.strip()) > 1]
    
    if is_question:
        # Join multi-line questions into a single sentence
        return [" ".join(cleaned)] if cleaned else []
    return cleaned

def get_ai_answer(question: str) -> str:
    """Asks Gemini for a concise trivia answer."""
    try:
        response = ai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"Answer this trivia question as concisely as possible (1-5 words max): {question}"
        )
        return f"[AI] {response.text.strip()}"
    except Exception as e:
        return f"[AI Error: {e}]"

def save_round_to_sheet(question: str, ai_answer: str, player_answers: list[str]):
    """Appends Question in Col A, AI Answer in Col B, and Player Answers in Col C+."""
    if not question:
        return
    row = [question, ai_answer] + player_answers
    worksheet.append_row(row, value_input_option="USER_ENTERED")
    print(f"--> Logged to Sheet: {row}\n")

# ==========================================
# MAIN BOT LOOP
# ==========================================
def run_bot():
    current_question = ""
    current_ai_answer = ""
    collected_answers = []

    print("Bot is live! Press Ctrl+C in the terminal to stop.\n")
    
    with mss.mss() as sct:
        try:
            while True:
                # 1. Read the center question box
                q_texts = capture_and_read(sct, QUESTION_REGION, is_question=True)
                detected_q = q_texts[0] if q_texts else ""

                # 2. Check if a NEW question appeared
                if detected_q and not is_similar(detected_q, current_question):
                    # Save the previous round before resetting
                    if current_question:
                        save_round_to_sheet(current_question, current_ai_answer, collected_answers)
                    
                    print(f"New Question Detected: {detected_q}")
                    current_question = detected_q
                    collected_answers = []
                    current_ai_answer = get_ai_answer(current_question)
                    print(f"Generated AI Answer: {current_ai_answer}")

                # 3. Read player answers floating on screen
                if current_question:
                    raw_bubbles = capture_and_read(sct, PLAYERS_REGION, is_question=False)
                    for bubble in raw_bubbles:
                        # Ignore the question itself if the players region overlaps the center
                        if is_similar(bubble, current_question, 0.65):
                            continue
                        
                        # Add only if we haven't already logged a similar answer this round
                        if not any(is_similar(bubble, existing) for existing in collected_answers):
                            collected_answers.append(bubble)
                            print(f"  + Player Answer: {bubble}")

                time.sleep(SCAN_INTERVAL_SEC)

        except KeyboardInterrupt:
            print("\nStopping bot... Saving final round.")
            if current_question:
                save_round_to_sheet(current_question, current_ai_answer, collected_answers)
            print("Done!")

if __name__ == "__main__":
    run_bot()