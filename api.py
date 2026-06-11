from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv
from neo4j import GraphDatabase
from extractor import process_contract
import PyPDF2
import io
import anthropic

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI"),
    auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD"))
)

@app.post("/analyze")
async def analyze_contract(file: UploadFile = File(...)):
    try:
        content = await file.read()
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(content))
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text()
        entities = process_contract(text, file.filename)
        return {"status": "success", "entities": entities}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/graph/{document_name}")
async def get_graph(document_name: str):
    """Get graph data for visualization"""
    with driver.session(database=os.getenv("NEO4J_DATABASE")) as session:
        result = session.run("""
            MATCH (d:Document {name: $name})-[r]->(n)
            RETURN d, r, n
        """, name=document_name)
        
        nodes = []
        edges = []
        seen_nodes = set()
        
        for record in result:
            doc = record["d"]
            rel = record["r"]
            node = record["n"]
            
            if doc.element_id not in seen_nodes:
                nodes.append({"id": doc.element_id, "label": doc["name"], "type": "Document"})
                seen_nodes.add(doc.element_id)
            
            if node.element_id not in seen_nodes:
                node_type = list(node.labels)[0]
                nodes.append({"id": node.element_id, "label": dict(node).get("name") or dict(node).get("description", "")[:50], "type": node_type})
                seen_nodes.add(node.element_id)
            
            edges.append({"from": doc.element_id, "to": node.element_id, "label": rel.type})
        
        return {"nodes": nodes, "edges": edges}

@app.get("/risks/{document_name}")
async def get_risks(document_name: str):
    """Get risks for a document"""
    with driver.session(database=os.getenv("NEO4J_DATABASE")) as session:
        result = session.run("""
            MATCH (d:Document {name: $name})-[:HAS_RISK]->(r:Risk)
            RETURN r.description as description, r.severity as severity
        """, name=document_name)
        return {"risks": [dict(record) for record in result]}

@app.get("/obligations/{document_name}")
async def get_obligations(document_name: str):
    """Get obligations for a document"""
    with driver.session(database=os.getenv("NEO4J_DATABASE")) as session:
        result = session.run("""
            MATCH (p:Party)-[:HAS_OBLIGATION]->(o:Obligation)
            MATCH (d:Document {name: $name})-[:CONTAINS]->(o)
            RETURN p.name as party, o.description as obligation, o.deadline as deadline
        """, name=document_name)
        return {"obligations": [dict(record) for record in result]}

@app.post("/query")
async def query_contract(document_name: str, question: str):
    """Query contract in natural language"""
    # Get graph context from Neo4j
    with driver.session(database=os.getenv("NEO4J_DATABASE")) as session:
        obligations = session.run("""
            MATCH (p:Party)-[:HAS_OBLIGATION]->(o:Obligation)
            MATCH (d:Document {name: $name})-[:CONTAINS]->(o)
            RETURN p.name as party, o.description as obligation, o.deadline as deadline
        """, name=document_name)
        
        risks = session.run("""
            MATCH (d:Document {name: $name})-[:HAS_RISK]->(r:Risk)
            RETURN r.description as description, r.severity as severity
        """, name=document_name)
        
        obligations_text = "\n".join([
            f"- {r['party']}: {r['obligation']} (deadline: {r['deadline']})"
            for r in obligations
        ])
        
        risks_text = "\n".join([
            f"- [{r['severity'].upper()}] {r['description']}"
            for r in risks
        ])
    
    context = f"""
Contract: {document_name}

OBLIGATIONS:
{obligations_text}

RISKS:
{risks_text}
"""
    
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=500,
        messages=[{
            "role": "user",
            "content": f"""Based on this contract data, answer the question concisely.

Contract data:
{context}

Question: {question}"""
        }]
    )
    
    return {
        "question": question,
        "answer": response.content[0].text,
        "document": document_name
    }

@app.post("/compare")
async def compare_contracts(document1: str, document2: str):
    """Compare obligations and risks between two contracts"""
    
    def get_contract_data(doc_name: str):
        with driver.session(database=os.getenv("NEO4J_DATABASE")) as session:
            obligations = list(session.run("""
                MATCH (p:Party)-[:HAS_OBLIGATION]->(o:Obligation)
                MATCH (d:Document {name: $name})-[:CONTAINS]->(o)
                RETURN p.name as party, o.description as obligation, o.deadline as deadline
            """, name=doc_name))
            
            risks = list(session.run("""
                MATCH (d:Document {name: $name})-[:HAS_RISK]->(r:Risk)
                RETURN r.description as description, r.severity as severity
            """, name=doc_name))
            
        return {
            "obligations": [dict(r) for r in obligations],
            "risks": [dict(r) for r in risks]
        }
    
    data1 = get_contract_data(document1)
    data2 = get_contract_data(document2)
    
    prompt = f"""Compare these two construction contracts and identify:
1. Obligations present in Contract 1 but missing in Contract 2
2. Obligations present in Contract 2 but missing in Contract 1
3. Risk differences between the two contracts
4. Overall risk assessment comparison

CONTRACT 1 ({document1}):
Obligations: {data1['obligations']}
Risks: {data1['risks']}

CONTRACT 2 ({document2}):
Obligations: {data2['obligations']}
Risks: {data2['risks']}

Provide a structured comparison with clear sections."""

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    
    return {
        "document1": document1,
        "document2": document2,
        "comparison": response.content[0].text,
        "contract1_data": data1,
        "contract2_data": data2
    }
@app.get("/risk-score/{document_name}")
async def get_risk_score(document_name: str):
    """Calculate overall risk score for a contract"""
    with driver.session(database=os.getenv("NEO4J_DATABASE")) as session:
        risks = list(session.run("""
            MATCH (d:Document {name: $name})-[:HAS_RISK]->(r:Risk)
            RETURN r.description as description, r.severity as severity
        """, name=document_name))
    
    risks_data = [dict(r) for r in risks]
    
    if not risks_data:
        return {"score": 0, "level": "NO DATA", "breakdown": {}}
    
    # Calculate score
    severity_weights = {"high": 10, "medium": 5, "low": 2}
    total_score = sum(severity_weights.get(r["severity"], 0) for r in risks_data)
    max_score = len(risks_data) * 10
    normalized_score = round((total_score / max_score) * 100) if max_score > 0 else 0
    
    breakdown = {
        "high": sum(1 for r in risks_data if r["severity"] == "high"),
        "medium": sum(1 for r in risks_data if r["severity"] == "medium"),
        "low": sum(1 for r in risks_data if r["severity"] == "low"),
        "total_risks": len(risks_data)
    }
    
    if normalized_score >= 70:
        level = "HIGH RISK"
        color = "#E74C3C"
    elif normalized_score >= 40:
        level = "MEDIUM RISK"
        color = "#F39C12"
    else:
        level = "LOW RISK"
        color = "#27AE60"
    
    return {
        "document": document_name,
        "score": normalized_score,
        "level": level,
        "color": color,
        "breakdown": breakdown
    }