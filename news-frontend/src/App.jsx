import React, { useState, useEffect } from 'react';
import { db } from './firebaseConfig';
import { collection, query, where, getDocs } from 'firebase/firestore';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, Zap, Quote, Newspaper, Loader2, Image as ImageIcon, Activity } from 'lucide-react';
import GraphVisualizer from './GraphVisualizer';
import './App.css';

export default function App() {
  const [news, setNews] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchTodayNews = async () => {
      setLoading(true);
      const today = new Date();
      const formattedDate = `${String(today.getUTCDate()).padStart(2, '0')}_${String(today.getUTCMonth() + 1).padStart(2, '0')}_${today.getUTCFullYear()}`;
      
      try {
        const q = query(
          collection(db, "daily_news"),
          where("date", ">=", formattedDate)
        );

        const querySnapshot = await getDocs(q);
        const articles = querySnapshot.docs.map(doc => ({ id: doc.id, ...doc.data() }));
        setNews(articles);
      } catch (err) {
        console.error("Firestore Error:", err);
        setError("Failed to load intelligence.");
      } finally {
        setLoading(false);
      }
    };
    fetchTodayNews();
  }, []);

  return (
    <div className="app-container">
      
      <header className="app-header">
        <div className="header-content">
          <div className="header-brand">
            <div className="brand-icon">
              <Zap size={16} />
            </div>
            <span className="brand-name">Nyusu</span>
          </div>
          <div className="header-status">
            <span>Status: {loading ? 'Fetching' : 'Active'}</span>
            <span className="status-dot" />
          </div>
        </div>
      </header>

      <main className="main-content">
        <h1 className="title"> <span className="redacted"> INTELOps</span></h1>
        <p className="subtitle"> <span className="redacted">Daily synthesized intelligence combining semantic entity extraction, historical analog mapping, and generative visual contexts.</span>
        </p>

        {loading && (
          <div className="loading-state">
            <Loader2 className="spinner" size={32} style={{ animation: 'logo-spin 2s linear infinite', color: '#f88', marginBottom: '1rem' }} />
            <span className="mono-label" style={{ margin: 0 }}>Compiling Intelligence...</span>
          </div>
        )}

        {error && (
          <div className="error-state">
            [ERROR]: {error}
          </div>
        )}

        <AnimatePresence>
          {!loading && news.map((item, index) => (
            <motion.div
              key={item.id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: index * 0.1 }}
              className="article-card frosted"
            >
              <div className="article-header">
                <div className="article-icon">
                  <Newspaper size={20} />
                </div>
                <div>
                  <h2 className="article-title">{item.title}</h2>
                  <div className="article-meta">
                    <span>ID: {item.cluster_id || item.id}</span>
                    <span>•</span>
                    <span>Extracted: {item.date}</span>
                  </div>
                </div>
              </div>

              <div className="article-body">
                
                <div className="article-text-col">
                  <div>
                    <h3 className="mono-label"><Search size={14} /> Raw Intelligence</h3>
                    <p className="content-paragraph">{item.summary}</p>
                  </div>
                  {item.image_url && (
                    <div>
                      <h3 className="mono-label"><ImageIcon size={14} /> Synthesized Frame</h3>
                      <div className="visual-container">
                        <img src={item.image_url} alt={item.title} className="generated-image" />
                        <div className="ai-badge">AI Generated</div>
                      </div>
                    </div>
                  )}
                  {item.matched_quote && (
                    <div className="quote-section">
                      <div className="quote-accent-bar" />
                      <h3 className="mono-label"><Quote size={14} /> Historical Context</h3>
                      <blockquote className="quote-text">"{item.matched_quote}"</blockquote>
                      <p className="quote-source">— {item.source_material}</p>
                    </div>
                  )}
                </div>

                <div className="article-visual-col">
                  
                  {item.graph && item.graph.nodes && item.graph.nodes.length > 0 && (
                    <div>
                      <h3 className="mono-label"><Activity size={14} /> Knowledge Graph</h3>
                      <GraphVisualizer graph={item.graph} />
                    </div>
                  )}

                  {item.analysis && (
                    <div>
                      <h3 className="mono-label"><Activity size={14} /> Strategic Analysis</h3>
                      <p className="content-paragraph">{item.analysis}</p>
                    </div>
                  )}

                </div>
              </div>
            </motion.div>
          ))}
        </AnimatePresence>

        {!loading && news.length === 0 && (
          <div className="empty-state">
            <span className="mono-label">No intelligence found for today.</span>
          </div>
        )}
      </main>

      <footer className="app-footer">
        <p className="footer-text">
          Nexus_Intel // Automated Wisdom Retrieval // v2.0
        </p>
      </footer>
    </div>
  );
}