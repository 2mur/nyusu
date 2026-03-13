import os
import json
from datetime import datetime, timezone, timedelta
from google.cloud import storage
from google import genai
from google.genai import types
from pinecone import Pinecone
from dotenv import load_dotenv

# Loads from .env if present locally; ignored in Cloud Run if omitted from Dockerfile
load_dotenv()

# --- CONFIGURATION ---
GCS_BUCKET = os.environ.get("GCS_BUCKET_NAME")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")

LLM_MODEL = os.environ.get("LLM_MODEL")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL")
STYLE_CONFIG = os.environ.get("STYLE_CONFIG", "")
MAX_ARTICLES = int(os.environ.get("MAX_ARTICLES"))

PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.environ.get("PINECONE_INDEX_NAME")
PINECONE_THRESHOLD = float(os.environ.get("PINECONE_THRESHOLD", "0.6"))


client = genai.Client(api_key=GOOGLE_API_KEY)
storage_client = storage.Client()
pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index(PINECONE_INDEX_NAME)
bucket = storage_client.bucket(GCS_BUCKET)

# --- RAW DICTIONARY SCHEMA ---
BATCH_ANALYSIS_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "analyses": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "cluster_id": {"type": "STRING"},
                    "consolidated_summary": {
                        "type": "STRING", 
                        "description": "A single, cohesive summary that removes redundancies from the raw concatenated news text."
                    },
                    "matched_quote": {
                        "type": "STRING",
                        "description": "The exact text of the quote ONLY. Do not include the author's name here."
                    },
                    "source_material": {
                        "type": "STRING",
                        "description": "The author and/or book the quote is from."
                    },
                    "analysis": {"type": "STRING"},
                    "graph": {
                        "type": "OBJECT",
                        "properties": {
                            "nodes": {
                                "type": "ARRAY",
                                "items": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "id": {"type": "STRING", "description": "Entity name."},
                                        "label": {"type": "STRING", "description": "Entity type."}
                                    },
                                    "required": ["id", "label"]
                                }
                            },
                            "edges": {
                                "type": "ARRAY",
                                "items": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "source": {"type": "STRING", "description": "Source node ID."},
                                        "target": {"type": "STRING", "description": "Target node ID."},
                                        "relation": {"type": "STRING", "description": "Relationship or action."}
                                    },
                                    "required": ["source", "target", "relation"]
                                }
                            }
                        },
                        "required": ["nodes", "edges"]
                    },
                    "image_prompt": {"type": "STRING"}
                },
                "required": [
                    "cluster_id", 
                    "consolidated_summary", 
                    "matched_quote", 
                    "source_material", 
                    "analysis", 
                    "graph", 
                    "image_prompt"
                ]
            }
        }
    },
    "required": ["analyses"]
}

def get_gcs_json(blob_name):
    blob = storage_client.bucket(GCS_BUCKET).blob(blob_name)
    return json.loads(blob.download_as_string()) if blob.exists() else None


def main():
    # 1. INFER DATE FROM BUCKET (Dynamically find the latest file)
    blobs = list(bucket.list_blobs(prefix="raw_news/"))
    if not blobs: 
        print("No files found in raw_news/. Exiting.")
        return
    
    def extract_date(blob):
        try:
            # Assumes format raw_news_DD_MM_YYYY.json
            date_str = blob.name.replace("raw_news/raw_news_", "").replace(".json", "")
            return datetime.strptime(date_str, "%d_%m_%Y")
        except:
            return datetime.min
        
    latest_blob = max(blobs, key=extract_date)

    curr_day = latest_blob.name.replace("raw_news/raw_news_", "").replace(".json", "")

    print(f"Inferred active date '{curr_day}' from {latest_blob.name}")
    
    news_blob = f"raw_news/raw_news_{curr_day}.json"
    output_blob = f"deep_news/deep_news_{curr_day}.json"
    
    news_data = get_gcs_json(news_blob)
    if not news_data:
        print("No news found.")
        return

    existing_results = get_gcs_json(output_blob) or []
    processed_ids = {item.get("cluster_id") for item in existing_results}
    
    target_news = sorted(news_data, key=lambda x: x.get("article_count", 0), reverse=True)[:MAX_ARTICLES]
    news_to_process = [n for n in target_news if n.get("cluster_id") not in processed_ids]
    
    if not news_to_process:
        print("All targeted articles processed.")
        return

    analysis_payload = []
    
    for article in news_to_process:
        # Embed the summary and query Pinecone
        emb_res = client.models.embed_content(
            model=EMBEDDING_MODEL, 
            contents=article["summary"],
            config=types.EmbedContentConfig(output_dimensionality=3072)
        )
        vector = emb_res.embeddings[0].values
        
        pc_res = index.query(vector=vector, top_k=1, include_metadata=True)
        
        if pc_res.matches and pc_res.matches[0].score >= PINECONE_THRESHOLD: 
            match = pc_res.matches[0].metadata
            analysis_payload.append({
                "cluster_id": article["cluster_id"],
                "news_summary": article["summary"],
                "provided_quote": match.get("original_quote", ""),
                "source_material": match.get("source_material", "Unknown")
            })
        else:
            analysis_payload.append({
                "cluster_id": article["cluster_id"],
                "news_summary": article["summary"],
                "provided_quote": "TRIGGER_FALLBACK",
                "source_material": "N/A"
            })

    # Execute Gemini Analysis with Summarization and Graph Instructions
    prompt = f"""Analyze this JSON list of news paired with strategic quotes. For EACH item, you must:
    1. Synthesize the 'news_summary' (which contains multiple concatenated reports) into a single, cohesive 'consolidated_summary' that eliminates all redundant information.
    2. Map the core entities and their actions as a Knowledge Graph (nodes and edges) using the synthesized facts.
    3. Output a comparative analysis of the news against the provided strategic quote.
    4. Generate a descriptive image prompt that strictly illustrates the actions described in your Knowledge Graph. If military, group of soldiers performing actions is mentioned, 
    include characters in heavy tactical combat uniforms, if politicians or business leaders are mentioned, put them in suits with goofy/crazed faces. 
    Do not include any artistic style in the image prompt, as it will be appended later. The locations in the article should be displayed as the gritty versio of the setting.
    STRICT REQUIREMENT - CHECK THAT I WONT HAVE ANY HARM_CATEGORY_DANGEROUS_CONTENT BEING TRIGGERED, 
    REWRITE the whole image prompt to ensure that I get some image back (remove reference to names, just use SAFE descriptions).
    
    CRITICAL QUOTE FORMATTING:
    If 'provided_quote' is 'TRIGGER_FALLBACK', generate a relevant quote from a historical Great book (war strategy, philosophy). 
    Whether using the provided quote or a generated fallback, you MUST separate the quote from the author. 
    Put ONLY the quote text in 'matched_quote', and put the author/book in 'source_material'. Do not append the author to the quote string.
    
    Data:
    {json.dumps(analysis_payload)}"""
    
    response = client.models.generate_content(
        model=LLM_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=BATCH_ANALYSIS_SCHEMA,
            temperature=0
        )
    )
    
    analyses = json.loads(response.text)
    
    for final_analysis in analyses["analyses"]:
        orig = next((n for n in news_to_process if n["cluster_id"] == final_analysis["cluster_id"]), {})
        existing_results.append({
            "cluster_id": final_analysis["cluster_id"],
            "title": orig.get("primary_title", "Unknown"),
            "summary": final_analysis["consolidated_summary"],
            "matched_quote": final_analysis["matched_quote"],
            "source_material": final_analysis["source_material"],
            "analysis": final_analysis["analysis"],
            "graph": final_analysis["graph"],
            "image_prompt": final_analysis["image_prompt"].strip() + " " + STYLE_CONFIG
        })

    storage_client.bucket(GCS_BUCKET).blob(output_blob).upload_from_string(json.dumps(existing_results, indent=2), content_type='application/json')
    print("Inference complete.")

if __name__ == "__main__":
    main()