import os
import json
from io import BytesIO
from datetime import datetime
from dotenv import load_dotenv
from PIL import Image
from google.cloud import storage
from google.cloud import firestore
from google import genai
from google.genai import types

# Loads from .env if present locally; ignored in Cloud Run if omitted from Dockerfile
load_dotenv()

# --- CONFIGURATION ---
GCS_BUCKET = os.environ.get("GCS_BUCKET_NAME")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
IMAGE_MODEL = os.environ.get("IMAGE_MODEL")

if not all([GCS_BUCKET, GOOGLE_API_KEY]):
    raise ValueError("Missing required environment variables.")

MAX_PROMPT_LENGTH = 13370

storage_client = storage.Client()
firestore_client = firestore.Client()
bucket = storage_client.bucket(GCS_BUCKET)
client = genai.Client(api_key=GOOGLE_API_KEY)

def generate_anime_image(base_prompt, img_id):
    
    style_suffix = (
        "Renditioned in a dark, gritty military anime style. black-ops military aesthetic, Desaturated, bleak color palette, stark contrast. "
        "Aesthetic of a serious war drama anime. Sleek but battle-worn. Sharp, precise linework. 1:1 square aspect ratio."
    )
    
    available_length = MAX_PROMPT_LENGTH - len(style_suffix) - 1 
    safe_prompt = base_prompt[:available_length].strip() + " " + style_suffix

    try:
        response = client.models.generate_content(
            model=IMAGE_MODEL,
            contents=safe_prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                # We can add a safety setting tweak here to prevent military gear from being flagged as 'violence'
                safety_settings=[
                    types.SafetySetting(
                        category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                        threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
                    )
                ]
            )
        )
        
        raw_bytes = None
        
        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.inline_data and part.inline_data.data:
                    raw_bytes = part.inline_data.data
                    break
        
        if not raw_bytes:
            print(f"Warning: Model returned no image data (likely safety filter). Prompt: {safe_prompt}")
            return None

        # Create and save the image
        pil_image = Image.open(BytesIO(raw_bytes))
        img_byte_arr = BytesIO()
        pil_image.save(f'{img_id}_img.png')
        pil_image.save(img_byte_arr, format='PNG')
        return img_byte_arr.getvalue()
    
    except Exception as e:
        print(f"Image API Error: {e}")
        return None

def main():
    # 1. INFER DATE FROM BUCKET (Dynamically find the latest file)
    blobs = list(bucket.list_blobs(prefix="deep_news/"))
    if not blobs: 
        print("No files found in deep_news/. Exiting.")
        return
        
    def extract_date(blob):
        try:
            # Assumes format deep_news_DD_MM_YYYY.json
            date_str = blob.name.replace("deep_news/deep_news_", "").replace(".json", "")
            return datetime.strptime(date_str, "%d_%m_%Y")
        except:
            return datetime.min

    latest_blob = max(blobs, key=extract_date)
    curr_day = latest_blob.name.replace("deep_news/deep_news_", "").replace(".json", "")
    print(f"Inferred active date '{curr_day}' from {latest_blob.name}")
    
    articles = json.loads(latest_blob.download_as_string())
    
    # 2. ITERATE AND PROCESS
    for article in articles:
        cluster_id = article["cluster_id"]
        doc_ref = firestore_client.collection("daily_news").document(cluster_id)
        
        if doc_ref.get().exists:
            print(f"Article {cluster_id} already exists in Firestore. Skipping.")
            continue
            
        print(f"Processing image for {cluster_id}...")
        image_url = None

        image_bytes = generate_anime_image(article["image_prompt"], cluster_id)
        
        if not image_bytes:
            print(f"Image generation failed/blocked for {cluster_id}. Saving article to Firestore without image.")
        else:
            # Upload the valid image and build URL
            blob_path = f"images/{cluster_id}.png"
            bucket.blob(blob_path).upload_from_string(image_bytes, content_type="image/png")
            image_url = f"https://storage.googleapis.com/{GCS_BUCKET}/{blob_path}"

        # Save to Firestore regardless of whether the image generated successfully
        doc_ref.set({
            "cluster_id": cluster_id,
            "title": article.get("title", ""),
            "summary": article.get("summary", ""),
            "date": curr_day, 
            "matched_quote": article.get("matched_quote", ""),
            "source_material": article.get("source_material", ""),
            "analysis": article.get("analysis", ""),
            "graph": article.get("graph", {}),
            "image_url": image_url,
            "timestamp": firestore.SERVER_TIMESTAMP
        })
        print(f"Saved {cluster_id} to Firestore.")

if __name__ == "__main__":
    main()