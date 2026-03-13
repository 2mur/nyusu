# Nyusu 📰 

Nyusu is an AI-powered full-stack application designed to ingest unstructured text (like news articles or books), process the data using Retrieval-Augmented Generation (RAG), and visualize the resulting entity relationships through an interactive web dashboard.

## System Architecture

### Backend (`/news-backend`)
A serverless Python pipeline designed for scalable cloud deployment.
* **Infrastructure**: Configured for containerization via Docker and orchestrated using Cloud Workflows.
* **AI & RAG**: Integrates Google GenAI for text inference and automated image generation.
* **Vector Storage**: Uses Pinecone for storing and querying text embeddings. Stores standard data in Google Cloud Storage.
* **Processing**: Leverages LangChain recursive character splitters for efficient text chunking.

### Frontend (`/news-frontend`)
A modern, reactive web application for exploring data relationships.
* **Framework**: React.js environment utilizing JSX.
* **Database**: Syncs data queries using Firebase Firestore.
* **Visualization**: Interactive network graphs built with D3.js to map relationships.

## Deployment

### Backend Setup (GCP)
1. Navigate to `/news-backend`.
2. Configure your `.env` file with your Pinecone and Google GenAI API credentials.
3. Build the environment using the provided `Dockerfile` and deploy to Cloud Run.
4. Deploy `workflow.yaml` to Google Cloud Workflows.

### Frontend Setup
1. Navigate to `/news-frontend`.
2. Run `npm install` to install Node dependencies.
3. Establish your Firebase connection parameters in a `firebaseConfig.js` file.
4. Run `npm run dev` to launch the local development server.