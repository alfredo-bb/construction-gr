import os
from dotenv import load_dotenv
from neo4j import GraphDatabase
import anthropic
import json

load_dotenv()

# Neo4j connection
driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI"),
    auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD"))
)

print(f"URI: {os.getenv('NEO4J_URI')}")
print(f"USER: {os.getenv('NEO4J_USERNAME')}")
print(f"PASS: {os.getenv('NEO4J_PASSWORD')}")

# Anthropic client
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def extract_entities(text: str) -> dict:
    """Extract entities from contract text using Claude"""
    prompt = f"""Analyze this construction contract text and extract entities and relationships.
    
Return ONLY a JSON object with this exact structure:
{{
    "parties": [
        {{"name": "company name", "role": "contractor/client/subcontractor"}}
    ],
    "obligations": [
        {{"party": "party name", "obligation": "description", "deadline": "date or null"}}
    ],
    "risks": [
        {{"description": "risk description", "severity": "high/medium/low"}}
    ],
    "clauses": [
        {{"number": "clause number", "title": "clause title", "summary": "brief summary"}}
    ]
}}

Contract text:
{text[:3000]}"""

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    
    response_text = response.content[0].text.strip()
    if response_text.startswith("```"):
        response_text = response_text.split("```")[1]
        if response_text.startswith("json"):
            response_text = response_text[4:]

    return json.loads(response_text.strip())

def save_to_neo4j(entities: dict, document_name: str):
    """Save extracted entities to Neo4j"""
    with driver.session(database="c66deed2") as session:
        # Create document node
        session.run(
            "MERGE (d:Document {name: $name})",
            name=document_name
        )
        
        # Create party nodes
        for party in entities.get("parties", []):
            session.run(
                """MERGE (p:Party {name: $name})
                SET p.role = $role
                WITH p
                MATCH (d:Document {name: $doc})
                MERGE (d)-[:INVOLVES]->(p)""",
                name=party["name"], role=party["role"], doc=document_name
            )
        
        # Create obligation nodes
        for i, obligation in enumerate(entities.get("obligations", [])):
            session.run(
                """MERGE (o:Obligation {id: $id})
                SET o.description = $description, o.deadline = $deadline
                WITH o
                MATCH (p:Party {name: $party})
                MERGE (p)-[:HAS_OBLIGATION]->(o)
                WITH o
                MATCH (d:Document {name: $doc})
                MERGE (d)-[:CONTAINS]->(o)""",
                id=f"{document_name}_obligation_{i}",
                description=obligation["obligation"],
                deadline=obligation.get("deadline", ""),
                party=obligation["party"],
                doc=document_name
            )
        
        # Create risk nodes
        for i, risk in enumerate(entities.get("risks", [])):
            session.run(
                """MERGE (r:Risk {id: $id})
                SET r.description = $description, r.severity = $severity
                WITH r
                MATCH (d:Document {name: $doc})
                MERGE (d)-[:HAS_RISK]->(r)""",
                id=f"{document_name}_risk_{i}",
                description=risk["description"],
                severity=risk["severity"],
                doc=document_name
            )

def process_contract(text: str, document_name: str):
    """Main function to process a contract"""
    print(f"Extracting entities from {document_name}...")
    entities = extract_entities(text)
    print(f"Found: {len(entities.get('parties', []))} parties, "
          f"{len(entities.get('obligations', []))} obligations, "
          f"{len(entities.get('risks', []))} risks")
    
    print("Saving to Neo4j...")
    save_to_neo4j(entities, document_name)
    print("Done!")
    
    return entities

if __name__ == "__main__":
    # Test with sample contract text
    sample_contract = """
    CONTRACT AGREEMENT
    
    This agreement is made between BuildCorp Ltd (Contractor) and 
    Nordic Real Estate AS (Client) for the construction of office building.
    
    CLAUSE 1 - OBLIGATIONS
    The Contractor shall complete the foundation work by March 15, 2025.
    The Client shall provide site access within 7 days of contract signing.
    
    CLAUSE 2 - RISKS
    Delay in material delivery may cause project delays.
    Weather conditions during winter may affect construction timeline.
    
    CLAUSE 3 - PAYMENT
    The Client shall pay 30% upfront and remaining upon completion.
    Late payment incurs 2% monthly interest.
    """
    
    result = process_contract(sample_contract, "sample_contract")
    print(f"\nExtracted entities: {json.dumps(result, indent=2)}")