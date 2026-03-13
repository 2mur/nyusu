import os
import uuid
import json
import time
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_text_splitters import RecursiveCharacterTextSplitter
from google import genai
from google.genai import types
from pinecone import Pinecone

# Loads from .env
load_dotenv()

# ==============================================================================
# --- CONFIGURATION ---
# ==============================================================================

PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.environ.get("PINECONE_INDEX_NAME")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")

if not all([GOOGLE_API_KEY, PINECONE_API_KEY]):
    raise ValueError("Missing GOOGLE_API_KEY or PINECONE_API_KEY in .env file.")

LLM_MODEL = os.environ.get("LLM_MODEL")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL")

BATCH_SIZE = 15 # Reduced slightly to ensure reliable structured JSON output
CHUNK_SIZE = 3000
CHUNK_OVERLAP = 100
RATE_LIMIT_SLEEP = 6 

# --- LOCAL PATHS ---
TARGET_FILE = "cloud-news-pipeline-lite/books/art-of-war.txt" 
LOCAL_PAYLOAD_DIR = "cloud-news-pipeline-lite/quote-embeddings/payloads"
# ==============================================================================

# --- SCHEMAS ---
class Node(BaseModel):
    id: str = Field(description="Entity name.")
    label: str = Field(description="Entity type.")

class Edge(BaseModel):
    source: str = Field(description="Source node ID.")
    target: str = Field(description="Target node ID.")
    relation: str = Field(description="Relationship.")

class KnowledgeGraph(BaseModel):
    nodes: list[Node]
    edges: list[Edge]

class SingleChunkSummary(BaseModel):
    chunk_id: str = Field(description="Original chunk ID.")
    strategic_summary: str = Field(description="Summarized strategic principles.")

class BatchSummaryParams(BaseModel):
    summaries: list[SingleChunkSummary]

class SingleQuoteAnalysis(BaseModel):
    chunk_id: str = Field(description="Original chunk ID.")
    source_material: str = Field(description="Source text/book.")
    original_quote: str = Field(description="Exact core quote.")
    meaning: str = Field(description="Strategic meaning.")
    graph: KnowledgeGraph

class BatchQuoteAnalysisParams(BaseModel):
    analyses: list[SingleQuoteAnalysis]

# --- INITIALIZATION ---
client = genai.Client(api_key=GOOGLE_API_KEY)
pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index(PINECONE_INDEX_NAME)

def main():
    if not os.path.exists(TARGET_FILE):
        raise FileNotFoundError(f"Missing file: {TARGET_FILE}")

    book_title = os.path.splitext(os.path.basename(TARGET_FILE))[0].replace("-", " ").title()
    print(f"Starting ingestion for: {book_title}")
    
    with open(TARGET_FILE, 'r', encoding='utf-8') as f:
        raw_text = f.read()
        docs = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP).create_documents([raw_text])
    
    os.makedirs(LOCAL_PAYLOAD_DIR, exist_ok=True)
    total_batches = (len(docs) // BATCH_SIZE) + 1
    
    for i in range(0, len(docs), BATCH_SIZE):
        batch_num = (i // BATCH_SIZE) + 1
        print(f"\nProcessing batch {batch_num}/{total_batches}...")
        
        batch_input = [{"chunk_id": f"chunk_{i+j}", "text": d.page_content} for j, d in enumerate(docs[i:i+BATCH_SIZE])]
        
        try:
            # 1. Summarization Phase
            summary_prompt = f"Analyze this JSON list of text chunks. Extract and summarize core strategic principles and profound quotes. Maintain chunk_id.\n\n{json.dumps(batch_input)}"
            summary_response = client.models.generate_content(
                model=LLM_MODEL,
                contents=summary_prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=BatchSummaryParams,
                    temperature=0
                )
            )
            summaries_json = summary_response.text

            # 2. Extraction Phase
            extractor_prompt = f"Analyze this JSON list of strategic summaries. Identify the core quote, explain its meaning, and map concepts as a strict knowledge graph. Set 'source_material' to '{book_title}'. Maintain chunk_id. Return empty graph if no strategy exists.\n\n{summaries_json}"
            analysis_response = client.models.generate_content(
                model=LLM_MODEL,
                contents=extractor_prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=BatchQuoteAnalysisParams,
                    temperature=0
                )
            )
            analyses_data = json.loads(analysis_response.text)
            
            pinecone_vectors = []
            
            # 3. Embedding and Storage Phase
            for analysis in analyses_data.get("analyses", []):
                # Skip chunks with no actionable strategic content
                if not analysis.get("graph", {}).get("edges"):
                    continue 

                quote_id = f"strategy_{uuid.uuid4().hex[:8]}"
                
                # Save the full graph payload locally
                local_json_path = os.path.join(LOCAL_PAYLOAD_DIR, f"{quote_id}.json")
                with open(local_json_path, 'w', encoding='utf-8') as f:
                    json.dump(analysis, f, indent=2)
                
                # Embed the meaning for vector search
                meaning_text = analysis.get("meaning", "")
                emb_res = client.models.embed_content(model=EMBEDDING_MODEL, contents=meaning_text)
                vector_values = emb_res.embeddings[0].values
                
                # Prepare data for Pinecone
                pinecone_vectors.append({
                    "id": quote_id,
                    "values": vector_values,
                    "metadata": {
                        "original_quote": analysis.get("original_quote", ""),
                        "source_material": analysis.get("source_material", ""),
                        "meaning": meaning_text
                    }
                })
            
            # 4. Upsert to Pinecone in batch
            if pinecone_vectors:
                index.upsert(vectors=pinecone_vectors)
                print(f"Upserted {len(pinecone_vectors)} quotes to Pinecone.")
                
        except Exception as e:
            print(f"Error processing batch {batch_num}: {e}")
        
        time.sleep(RATE_LIMIT_SLEEP)

    print("\nIngestion complete.")

if __name__ == "__main__":
    main()