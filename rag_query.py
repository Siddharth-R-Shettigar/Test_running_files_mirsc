import chromadb
from sentence_transformers import SentenceTransformer

# Initialize
client = chromadb.PersistentClient(path="./data/rag")
model = SentenceTransformer('all-MiniLM-L6-v2')

def query_fraud_patterns(doc_type, detector_results, n_results=3):
    """
    Retrieves similar past fraud cases from case_logs index.
    Call this after detectors run, before llm_fusion.
    """
    try:
        collection = client.get_collection("fraud_patterns")
        count = collection.count()
        if count == 0:
            return {"retrieved": False, "reason": "No fraud patterns indexed yet"}

        query_text = f"""
        Document type: {doc_type}
        Detector findings: {str(detector_results)}
        """

        embedding = model.encode(query_text).tolist()

        results = collection.query(
            query_embeddings=[embedding],
            n_results=min(n_results, count)
        )

        cases = []
        for i, doc in enumerate(results['documents'][0]):
            cases.append({
                "source": results['metadatas'][0][i]['source'],
                "similarity": round(1 - results['distances'][0][i], 4),
                "content": doc[:500]
            })

        return {
            "retrieved": True,
            "similar_cases": cases,
            "count": len(cases)
        }

    except Exception as e:
        return {"retrieved": False, "reason": str(e)}


def query_document_standards(doc_type, country=None):
    """
    Retrieves official document standards for validation.
    Call this before field_validator and national_id_validator.
    """
    try:
        collection = client.get_collection("document_standards")

        query_text = f"{doc_type} {country or ''} document standards validation rules MRZ fields"
        embedding = model.encode(query_text).tolist()

        results = collection.query(
            query_embeddings=[embedding],
            n_results=2
        )

        standards = []
        for i, doc in enumerate(results['documents'][0]):
            standards.append({
                "type": results['metadatas'][0][i]['type'],
                "similarity": round(1 - results['distances'][0][i], 4),
                "content": doc
            })

        return {
            "retrieved": True,
            "standards": standards,
            "count": len(standards)
        }

    except Exception as e:
        return {"retrieved": False, "reason": str(e)}


def query_security_features(doc_type):
    """
    Retrieves expected security features for a document type.
    Call this before vision_llm_inspector.
    """
    try:
        collection = client.get_collection("document_standards")

        query_text = f"{doc_type} security features hologram microtext UV guilloché watermark"
        embedding = model.encode(query_text).tolist()

        results = collection.query(
            query_embeddings=[embedding],
            n_results=2
        )

        features = []
        for i, doc in enumerate(results['documents'][0]):
            features.append({
                "type": results['metadatas'][0][i]['type'],
                "content": doc
            })

        return {
            "retrieved": True,
            "expected_features": features
        }

    except Exception as e:
        return {"retrieved": False, "reason": str(e)}


def build_rag_context(doc_type, country, detector_results):
    """
    Master function — call this once from kavach_engine.py.
    Returns full RAG context to inject into LLM prompt.
    """
    fraud = query_fraud_patterns(doc_type, detector_results)
    standards = query_document_standards(doc_type, country)
    features = query_security_features(doc_type)

    context = []

    if standards['retrieved']:
        context.append("DOCUMENT STANDARDS:")
        for s in standards['standards']:
            context.append(s['content'])

    if features['retrieved']:
        context.append("\nEXPECTED SECURITY FEATURES:")
        for f in features['expected_features']:
            context.append(f['content'])

    if fraud['retrieved'] and fraud['count'] > 0:
        context.append("\nSIMILAR PAST FRAUD CASES:")
        for case in fraud['similar_cases']:
            context.append(f"Case: {case['source']} (similarity: {case['similarity']})")
            context.append(case['content'])

    return "\n".join(context)


if __name__ == "__main__":
    # Test the RAG query
    print("Testing RAG Query System")
    print("========================")

    test_results = {
        "ela_score": 0.73,
        "copy_move": True,
        "mrz_consistent": False
    }

    context = build_rag_context(
        doc_type="Indian Passport",
        country="India",
        detector_results=test_results
    )

    print(context)