import os
import uuid
import json
import requests
import numpy as np
from datetime import datetime, timezone, timedelta
from google.cloud import storage
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Loads from .env if present locally; ignored in Cloud Run if omitted from Dockerfile
load_dotenv()

# --- CONFIGURATION ---
THENEWSAPI_TOKEN = os.environ.get("THENEWSAPI_API_KEY")
NEWSDATA_API_KEY = os.environ.get("NEWSDATA_API_KEY")

GCS_BUCKET = os.environ.get("GCS_BUCKET_NAME")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL")

SIMILARITY_THRESHOLD = float(os.environ.get("SIMILARITY_THRESHOLD", "0.65"))

client = genai.Client(api_key=GOOGLE_API_KEY)

NUMCALLS_THENEWS = 50 # 50 * 3 
NUMCALLS_NEWSDATAIO = 15 # 15 * 10 

# Core geopolitical constraints
CONFLICT_KEYWORDS = [
    "china", "iran", "war", "conflict", "russia", "ukraine", 
    "israel", "gaza", "taiwan", "military", "attack", 
    "strike", "missile", "troops", "geopolitical", "tensions"
]

def fetch_thenewsapi():
    if not THENEWSAPI_TOKEN: return []
    articles, page = [], 1
    while page <= NUMCALLS_THENEWS:
        res = requests.get("https://api.thenewsapi.com/v1/news/top", params={
            "api_token": THENEWSAPI_TOKEN, "locale": "ca,gb,us", "categories": "politics",
            "exclude_categories": "science,sports,health,entertainment,tech,food,travel",
            "language": "en", "limit": 3, "page": page
        }).json()
        for item in res.get("data", []):
            articles.append({
                "id": str(uuid.uuid4()), "title": item.get("title", ""), "summary": item.get("description", ""),
                "url": item.get("url", ""), "source": item.get("source", ""), "original_source_api": "thenewsapi"
            })
        if res.get("meta", {}).get("returned", 0) < 3: break
        page += 1
    return articles

def fetch_newsdataio():
    if not NEWSDATA_API_KEY: return []
    articles, calls, next_page = [], 0, None
    while calls < NUMCALLS_NEWSDATAIO:
        params = {"apikey": NEWSDATA_API_KEY, "country": "ca,gb,us", "language": "en", "category": "world, politics"}
        if next_page: params["page"] = next_page
        res = requests.get("https://newsdata.io/api/1/latest", params=params).json()
        for item in res.get("results", []):
            articles.append({
                "id": str(uuid.uuid4()), "title": item.get("title", ""), "summary": item.get("description", ""),
                "url": item.get("link", ""), "source": item.get("source_id", ""), "original_source_api": "newsdata.io"
            })
        next_page = res.get("nextPage")
        if not next_page: break
        calls += 1
    return articles

def filter_conflict_articles(articles):
    filtered = []
    for a in articles:
        # Cast to lowercase for case-insensitive keyword matching
        text = f"{a.get('title', '')} {a.get('summary', '')}".lower()
        if any(kw in text for kw in CONFLICT_KEYWORDS):
            filtered.append(a)
    return filtered

def embed_texts(texts):
    response = client.models.embed_content(model=EMBEDDING_MODEL, contents=texts, config=types.EmbedContentConfig(output_dimensionality=3072))
    return np.array([emb.values for emb in response.embeddings])

def cluster_and_merge(articles):
    if not articles: return []
    
    texts = [f"{a['title']}. {a['summary']}" for a in articles]
    embeddings = embed_texts(texts)
    
    # Compute dot product for cosine similarity (Gemini embeddings are normalized)
    cosine_scores = np.dot(embeddings, embeddings.T)
    
    clusters, used = [], set()
    for i in range(len(articles)):
        if i in used: continue
        
        similar_indices = np.where(cosine_scores[i] >= SIMILARITY_THRESHOLD)[0].tolist()
        group = [articles[idx] for idx in similar_indices if idx not in used]
        used.update(similar_indices)
        
        if group:
            clusters.append({
                "cluster_id": str(uuid.uuid4()),
                "primary_title": group[0]["title"],
                "article_count": len(group),
                "summary": "\n\n".join([f"{a['title']} ({a['source']}): {a['summary']}" for a in group])
            })
    return clusters

def main():
    target_time = datetime.now(timezone.utc) + timedelta(hours=24)
    curr_day = target_time.strftime("%d_%m_%Y")
    blob_name = f"raw_news/raw_news_{curr_day}.json"
    
    storage_client = storage.Client()
    bucket = storage_client.bucket(GCS_BUCKET)
    if bucket.blob(blob_name).exists():
        print(f"Today's {curr_day} news already ingested.")
        return

    articles = fetch_thenewsapi() + fetch_newsdataio()
    if not articles:
        print("Failed to pull from APIs.")
        return

    # Execute the keyword filtration before generating embeddings
    filtered_articles = filter_conflict_articles(articles)
    if not filtered_articles:
        print("Zero articles matched the global conflict criteria. Halting ingestion.")
        return

    clustered = cluster_and_merge(filtered_articles)
    bucket.blob(blob_name).upload_from_string(json.dumps(clustered, indent=2), content_type='application/json')
    print(f"Filtered {len(articles)} raw articles into {len(filtered_articles)} matches.")
    print(f"Saved {len(clustered)} semantic clusters to GCS.")

if __name__ == "__main__":
    main()