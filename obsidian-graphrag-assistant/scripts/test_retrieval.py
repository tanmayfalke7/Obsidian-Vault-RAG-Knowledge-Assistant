"""
Script: test_retrieval.py
Tests the full GraphRAG retrieval pipeline with sample questions.
"""
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.config import settings, configure_logging
from backend.db.neo4j_client import init_driver, close_driver
from backend.services.embedding_service import init_embedding_service
from backend.services.llm_service import init_llm_service
from backend.services.rag_service import ask

configure_logging()
logger = logging.getLogger(__name__)

DEMO_QUESTIONS = [
    "What is RAG?",
    "How are embeddings related to vector search?",
    "What should I learn before GraphRAG?",
    "Find the relationship path from RAG to semantic search.",
    "What role does Neo4j play in this system?",
]


def main():
    print(f"\n{'='*60}")
    print("GraphRAG Retrieval Test")
    print(f"{'='*60}\n")

    init_driver(settings.neo4j_uri, settings.neo4j_username, settings.neo4j_password)
    init_embedding_service(settings.embedding_model)
    init_llm_service(settings.gemini_api_key or settings.groq_api_key, settings.gemini_llm_model)

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", default="system")
    args = parser.parse_args()

    for i, question in enumerate(DEMO_QUESTIONS, 1):
        print(f"\nQ{i}: {question}")
        print("-" * 50)
        try:
            result = ask(question, user_id=args.user_id)
            print(f"Answer:\n{result.answer}\n")
            if result.sources:
                print("Sources:")
                for s in result.sources:
                    score_str = f" ({s.get('score', 0):.3f})" if s.get('score') else ""
                    print(f"  📄 {s.get('filename', s.get('title','?'))}{score_str}")
            if result.relationships:
                print("\nGraph context:")
                for r in result.relationships[:5]:
                    print(f"  {r['source']} --[{r['relationship']}]--> {r['target']}")
        except Exception as e:
            print(f"❌ Failed: {e}")
        print()

    close_driver()
    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()
