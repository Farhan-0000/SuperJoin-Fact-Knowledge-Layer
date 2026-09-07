**Build a provenance-first, asynchronous, two-pass fact pipeline.**

> Do not build an autonomous agent, graph-first system, or generic RAG chatbot.

---

# **1\. The architecture I recommend**

                        ┌───────────────────────┐  
                         │      Web UI            │  
                         │   Streamlit / React    │  
                         └──────────┬────────────┘  
                                    │  
                                    ▼  
                         ┌───────────────────────┐  
                         │      FastAPI API       │  
                         │                       │  
                         │ Upload / Jobs / Facts │  
                         │ Relationships / Docs │  
                         └──────────┬────────────┘  
                                    │  
                                    ▼  
                         ┌───────────────────────┐  
                         │    Job Orchestrator    │  
                         │                       │  
                         │ queued → running      │  
                         │ → completed/failed    │  
                         └──────────┬────────────┘  
                                    │  
              ┌─────────────────────┼─────────────────────┐  
              │                     │                     │  
              ▼                     ▼                     ▼  
       ┌────────────┐        ┌──────────────┐       ┌────────────┐  
       │ PDF Parser │        │ LLM Service  │       │ Embedding  │  
       │  PyMuPDF   │        │ Structured   │       │  Service   │  
       │            │        │ extraction \+ │       │            │  
       │ pages      │        │ relationship │       │ candidates  │  
       │ blocks     │        │ judgment     │       │             │  
       │ tables     │        │              │       │             │  
       └─────┬──────┘        └──────┬───────┘       └─────┬──────┘  
             │                      │                     │  
             └──────────────────────┼─────────────────────┘  
                                    ▼  
                         ┌───────────────────────┐  
                         │      SQLite           │  
                         │                       │  
                         │ documents             │  
                         │ pages                 │  
                         │ blocks                │  
                         │ chunks                │  
                         │ facts                 │  
                         │ entities              │  
                         │ aliases               │  
                         │ embeddings            │  
                         │ candidates             │  
                         │ relationships         │  
                         │ jobs / cache          │  
                         └───────────────────────┘

The pipeline itself:

PDF  
 │  
 ▼  
1\. INGEST  
 │   SHA-256  
 │   page extraction  
 │   layout blocks  
 │   tables  
 │  
 ▼  
2\. CLEAN / STRUCTURE  
 │   remove repeated headers/footers  
 │   identify headings  
 │   detect low-text/scanned pages  
 │  
 ▼  
3\. CHUNK  
 │   semantic/layout-aware  
 │   page-aware  
 │   context overlap  
 │  
 ▼  
4\. FACT EXTRACTION  
 │   structured LLM output  
 │   exact evidence  
 │   page/block references  
 │  
 ▼  
5\. VALIDATE  
 │   Pydantic  
 │   evidence verification  
 │   reject/flag unsupported claims  
 │  
 ▼  
6\. NORMALIZE  
 │   units  
 │   numbers  
 │   dates  
 │   entities  
 │   predicates  
 │  
 ▼  
7\. DEDUPLICATE  
 │   same-document duplicates  
 │  
 ▼  
8\. INDEX  
 │   lexical index  
 │   embeddings  
 │  
 ▼  
9\. CANDIDATE GENERATION  
 │   entity/predicate filters  
 │   semantic similarity  
 │   same/different documents  
 │  
 ▼  
10\. RELATIONSHIP JUDGMENT  
 │    deterministic context checks  
 │    LLM verification  
 │  
 ▼  
11\. RELATIONSHIP VALIDATION  
 │    evidence references  
 │    confidence  
 │    uncertainty  
 │  
 ▼  
12\. UI/API

This is directly aligned with the requirement to extract meaningful facts, ground every fact in its source, and determine corroboration/contradiction/reconciliation.

---

# **2\. Why PyMuPDF should be the foundation**

I would use **PyMuPDF first**, not an LLM as the primary PDF parser.

It gives you page-level extraction and text blocks with bounding boxes, and it can reorder text top-to-bottom/left-to-right with `sort=True`. Its current documentation also provides `Page.find_tables()` for table detection/extraction. ([PyMuPDF](https://pymupdf.readthedocs.io/en/latest/app1.html?utm_source=chatgpt.com))

That matters because your provenance model can retain:

Document 3  
Page 47  
Block 12  
bbox \= \[x0, y0, x1, y1\]  
quote \= "..."

rather than merely:

source \= "document3.pdf"

For the assignment, this is a very strong design decision because source evidence is a core requirement.

---

# **3\. What the internal document representation should be**

Don't go directly:

PDF → text → LLM

Create a persistent intermediate representation.

## **Document**

Document  
├── id  
├── filename  
├── sha256  
├── size\_bytes  
├── page\_count  
├── status  
├── title  
├── document\_type  
├── published\_date  
├── reporting\_period  
├── created\_at  
└── metadata

## **Page**

Page  
├── id  
├── document\_id  
├── page\_number  
├── width  
├── height  
├── raw\_text  
├── cleaned\_text  
├── text\_quality  
├── is\_scanned  
└── metadata

## **Block**

Block  
├── id  
├── page\_id  
├── block\_index  
├── type  
├── text  
├── x0  
├── y0  
├── x1  
├── y1  
└── reading\_order

Types:

paragraph  
heading  
table  
caption  
list  
header  
footer  
unknown

For a table:

TableBlock  
├── headers  
├── rows  
├── bbox  
└── raw\_text  
---

# **4\. Chunk schema**

This is the object that actually gets sent to the extraction model.

class Chunk(BaseModel):  
    id: str  
    document\_id: str

    sequence\_index: int

    start\_page: int  
    end\_page: int

    block\_ids: list\[str\]

    heading\_path: list\[str\]

    text: str

    token\_count: int

    previous\_chunk\_id: str | None \= None  
    next\_chunk\_id: str | None \= None

    has\_table: bool \= False  
    has\_low\_quality\_page: bool \= False

    content\_hash: str

    extraction\_status: Literal\[  
        "pending",  
        "processing",  
        "completed",  
        "failed"  
    \]

### **Important design choice**

Use **semantic/layout chunks**, not "every 5 pages".

Something like:

Section Heading  
    paragraph  
    paragraph  
    table  
    paragraph

with a token ceiling.

Target roughly:

\~1,000–2,500 tokens

and use small overlap where necessary.

The overlap is for context, but the extraction result must identify exactly which current chunk text supports the claim.

---

# **5\. Fact schema**

This is the most important schema in the application.

I would divide a fact into five conceptual areas:

identity  
meaning  
value  
context  
provenance

### **Pydantic representation**

class Fact(BaseModel):  
    id: str

    document\_id: str  
    chunk\_id: str

    \# Meaning  
    subject: str  
    subject\_mention: str

    predicate: str  
    predicate\_mention: str

    \# Value  
    value\_text: str  
    value\_type: Literal\[  
        "number",  
        "currency",  
        "percentage",  
        "date",  
        "duration",  
        "boolean",  
        "text",  
        "quantity",  
        "range"  
    \]

    numeric\_value: float | None \= None  
    normalized\_numeric\_value: float | None \= None

    unit: str | None \= None  
    normalized\_unit: str | None \= None

    currency: str | None \= None

    \# Temporal context  
    time\_text: str | None \= None  
    time\_start: str | None \= None  
    time\_end: str | None \= None  
    time\_granularity: Literal\[  
        "day",  
        "month",  
        "quarter",  
        "half",  
        "year",  
        "fiscal\_year",  
        "unknown"  
    \] | None \= None

    \# Scope  
    geography: str | None \= None  
    scope: str | None \= None

    qualifiers: list\[str\] \= \[\]

    \# Provenance  
    source\_quote: str  
    source\_page\_start: int  
    source\_page\_end: int  
    source\_block\_ids: list\[str\]

    \# Quality  
    extraction\_confidence: float  
    validation\_status: Literal\[  
        "validated",  
        "warning",  
        "rejected"  
    \]

    extraction\_notes: list\[str\] \= \[\]  
---

# **6\. Don't hard-code a fact schema around the three PDFs**

This is a trap.

Don't write:

class FinancialFact:  
    revenue  
    employee\_count  
    ceo  
    headquarters

The assignment explicitly warns that evaluators may provide additional PDFs and says the solution should not depend on hard-coded facts, filenames, schemas, or document-specific rules.

Instead:

subject  
predicate  
value  
context

is your generic fact representation.

So the system can discover:

revenue  
employee\_count  
director  
headquarters  
acquisition  
product\_launch  
market\_share  
manufacturing\_capacity

without changing the database.

---

# **7\. Provenance should be stronger than just a quote**

Store both:

source\_quote

and:

source\_block\_ids

and:

page\_start  
page\_end

Eventually you can reconstruct the visual position.

The ideal UI should be able to say:

Revenue  
$8.2 billion  
FY2025

Source  
Annual\_Report.pdf  
Page 47

"Revenue for fiscal year 2025 was $8.2 billion."

Evidence confidence: HIGH

This directly supports the required evidence demonstration.

---

# **8\. A very important validation step**

After the LLM produces:

{  
  "source\_quote": "Revenue was $8.2 billion.",  
  "source\_page": 47  
}

your Python code should verify it.

At minimum:

quote\_normalized in page\_text\_normalized

If it cannot find the quote:

validation\_status \= "warning"

or, if clearly fabricated:

validation\_status \= "rejected"

This is a major protection against hallucinated provenance.

The model should **never be the final authority on whether its own evidence exists**.

---

# **9\. Entity schema**

Entity resolution is necessary for:

Acme Corporation  
Acme Corp.  
Acme  
the company  
the Group

Use:

class Entity(BaseModel):  
    id: str

    canonical\_name: str

    entity\_type: Literal\[  
        "person",  
        "organization",  
        "company",  
        "location",  
        "product",  
        "other"  
    \]

    aliases: list\[str\]

    confidence: float

And for each fact:

entity\_id

instead of relying solely on the raw subject string.

But don't force uncertain entity matches.

That's important.

---

# **10\. Predicate normalization**

Likewise:

revenue  
annual revenue  
sales  
net sales  
total revenue

may or may not mean the same thing.

Do **not** blindly map all of those to `revenue`.

Instead maintain:

PredicateMapping  
├── raw\_predicate  
├── canonical\_predicate  
├── confidence  
└── rationale

Then relationship reasoning can say:

predicate\_match \= "likely\_same\_metric"

rather than pretending certainty.

---

# **11\. Numeric normalization**

Build deterministic Python functions for:

1.2 billion  
1,200 million  
1,200,000,000  
USD 1.2B  
$1.2 bn

→

1200000000  
USD

Similarly:

2.5%  
0.025  
2.5 percent

can be represented consistently.

The LLM should extract the original expression.

Python should perform the numerical normalization.

That's an important division of labor.

---

# **12\. Dates and periods need their own representation**

Don't just store:

"FY2025"

as the only thing.

Store:

time\_text \= "FY2025"

time\_start \= "2024-04-01"  
time\_end \= "2025-03-31"

time\_granularity \= "fiscal\_year"

when the dates can be determined.

If they cannot, retain the original text and leave normalized dates null.

Never invent dates.

---

# **13\. Relationships should be evidence-bearing objects**

Use:

class Relationship(BaseModel):  
    id: str

    fact\_a\_id: str  
    fact\_b\_id: str

    relationship\_type: Literal\[  
        "corroborates",  
        "contradicts",  
        "reconciles",  
        "uncertain",  
        "unrelated"  
    \]

    confidence: float

    primary\_dimension: Literal\[  
        "value",  
        "time",  
        "scope",  
        "unit",  
        "entity",  
        "definition",  
        "geography",  
        "other"  
    \]

    context\_comparison: dict

    explanation: str

    evidence\_fact\_a: str  
    evidence\_fact\_b: str

    reasoning\_version: str

For example:

{  
  "relationship\_type": "reconciles",  
  "primary\_dimension": "time",  
  "context\_comparison": {  
    "period\_a": "FY2025",  
    "period\_b": "Q4 FY2025",  
    "period\_match": false  
  },  
  "explanation": "The figures differ because the first covers the full fiscal year while the second covers only Q4."  
}

This is considerably better than just:

A \--\[RECONCILES\]--\> B  
---

# **14\. Candidate-pair schema**

Before asking the LLM to reason, create:

class CandidatePair(BaseModel):  
    id: str

    fact\_a\_id: str  
    fact\_b\_id: str

    same\_document: bool

    entity\_similarity: float  
    predicate\_similarity: float  
    semantic\_similarity: float

    unit\_compatible: bool | None  
    period\_compatible: bool | None  
    scope\_compatible: bool | None

    candidate\_score: float

    reason\_selected: list\[str\]

    status: Literal\[  
        "pending",  
        "evaluated",  
        "skipped"  
    \]

This creates an explainable distinction between:

> "These two facts were compared"

and:

> "These two random facts happened to be compared by an LLM."

---

# **15\. Why candidate generation is essential**

Suppose extraction yields 1,000 facts.

Naively:

1,000 × 1,000

is huge.

Instead:

Fact A  
 │  
 ├── entity filter  
 ├── predicate filter  
 ├── document filter  
 └── embedding similarity  
           │  
           ▼  
    3–10 candidates

Then only those candidates go to the expensive reasoning stage.

OpenAI's current embedding documentation explicitly supports using embedding vectors for semantic search/similarity and documents `text-embedding-3-small`; it also documents cosine-similarity-style retrieval. ([OpenAI Platform](https://platform.openai.com/docs/guides/embeddings))

For your scale, you don't need a dedicated vector database.

---

# **16\. SQLite \+ FTS5 is enough**

Use SQLite.

Add FTS5 for searchable textual fields. SQLite documents FTS5 as its full-text search extension. ([SQLite](https://www.sqlite.org/fts5.html?utm_source=chatgpt.com))

You can store structured metadata as ordinary columns and flexible qualifiers as JSON; SQLite also has JSON support. ([SQLite](https://sqlite.org/json1.html?utm_source=chatgpt.com))

For embeddings:

fact\_embeddings  
\---------------  
fact\_id  
model  
dimensions  
vector\_blob  
content\_hash

You don't need Pinecone, Weaviate, Qdrant, Milvus, etc. for this assignment.

---

# **17\. The database schema**

I would implement these tables:

documents  
──────────  
id  
filename  
original\_filename  
sha256  
file\_size  
page\_count  
title  
document\_type  
published\_date  
reporting\_period  
status  
created\_at  
updated\_at

pages  
─────  
id  
document\_id  
page\_number  
width  
height  
raw\_text  
cleaned\_text  
text\_quality  
is\_scanned

blocks  
──────  
id  
page\_id  
block\_index  
block\_type  
text  
x0  
y0  
x1  
y1  
reading\_order  
content\_hash

chunks  
──────  
id  
document\_id  
sequence\_index  
start\_page  
end\_page  
block\_ids\_json  
heading\_path\_json  
text  
token\_count  
content\_hash  
status

facts  
─────  
id  
document\_id  
chunk\_id  
subject  
subject\_mention  
entity\_id  
predicate  
predicate\_mention  
value\_text  
value\_type  
numeric\_value  
normalized\_numeric\_value  
unit  
normalized\_unit  
currency  
time\_text  
time\_start  
time\_end  
time\_granularity  
scope  
geography  
qualifiers\_json  
source\_quote  
source\_page\_start  
source\_page\_end  
source\_block\_ids\_json  
extraction\_confidence  
validation\_status  
extraction\_notes\_json

entities  
────────  
id  
canonical\_name  
entity\_type  
confidence

entity\_aliases  
───────────────  
entity\_id  
alias  
confidence

fact\_embeddings  
────────────────  
fact\_id  
model  
dimensions  
vector\_blob  
content\_hash

candidate\_pairs  
───────────────  
id  
fact\_a\_id  
fact\_b\_id  
entity\_similarity  
predicate\_similarity  
semantic\_similarity  
unit\_compatible  
period\_compatible  
scope\_compatible  
candidate\_score  
reason\_json  
status

relationships  
─────────────  
id  
fact\_a\_id  
fact\_b\_id  
relationship\_type  
confidence  
primary\_dimension  
context\_comparison\_json  
explanation  
evidence\_fact\_a  
evidence\_fact\_b  
reasoning\_version

jobs  
────  
id  
job\_type  
status  
progress  
current\_stage  
total\_items  
completed\_items  
error\_message  
created\_at  
started\_at  
completed\_at

llm\_cache  
─────────  
id  
operation  
model  
prompt\_version  
input\_hash  
response\_json  
created\_at  
---

# **18\. Caching strategy**

This is extremely important given the deadline.

You want caching at **three levels**.

## **Level 1: document cache**

sha256(pdf)

Same PDF → don't re-ingest.

## **Level 2: extraction cache**

hash(  
    chunk\_text  
    \+ chunk\_structure  
    \+ extraction\_prompt\_version  
    \+ model  
)

Same chunk/prompt/model → reuse extraction.

## **Level 3: relationship cache**

hash(  
    normalized\_fact\_A  
    \+ normalized\_fact\_B  
    \+ relationship\_prompt\_version  
    \+ model  
)

Same relationship → reuse result.

---

# **19\. Prompt versioning is mandatory**

Don't cache merely on:

chunk\_hash

Use:

chunk\_hash  
\+  
prompt\_version  
\+  
model

Suppose:

EXTRACTION\_PROMPT\_VERSION \= "v3"

and you change it to:

"v4"

the system should automatically regenerate extraction.

This will save you an enormous amount of time while iterating.

---

# **20\. Don't use OpenAI Batch API during the actual demo**

The Batch API is useful for large offline workloads, but it is asynchronous and currently documents a 24-hour completion window. ([OpenAI Platform](https://platform.openai.com/docs/api-reference/batch/object?api-mode=responses&utm_source=chatgpt.com))

That makes it inappropriate for the evaluator's interactive:

Upload PDFs  
→ Process  
→ See results

experience.

Use normal asynchronous API calls with limited concurrency.

You can mention Batch as a future scalability option in the README.

---

# **21\. FastAPI job model**

A 300-page processing request should not block an HTTP request until everything is complete.

The API should immediately return:

202 Accepted  
{  
    "job\_id": "job\_abc",  
    "status": "queued"  
}

FastAPI supports background tasks for returning a response while processing continues, including document processing; its documentation also notes that heavier/distributed workloads may warrant a queue such as Celery, but for this prototype a local job runner is enough. ([FastAPI](https://fastapi.tiangolo.com/tutorial/background-tasks/?utm_source=chatgpt.com))

So:

POST /v1/ingestions  
       ↓  
202  
       ↓  
background job  
       ↓  
GET /v1/jobs/{id}  
---

# **22\. Exact API**

I recommend this API contract.

## **Health**

GET /health

Response:

{  
  "status": "ok",  
  "version": "0.1.0"  
}  
---

## **Upload documents**

POST /v1/documents  
Content-Type: multipart/form-data  
files: multiple PDF files

Response:

{  
  "documents": \[  
    {  
      "id": "doc\_123",  
      "filename": "report.pdf",  
      "page\_count": 100,  
      "status": "uploaded"  
    }  
  \]  
}

FastAPI's `UploadFile` is specifically designed for uploaded files and uses a spooled file rather than holding the entire file in memory, making it suitable for larger uploads. ([FastAPI](https://fastapi.tiangolo.com/tutorial/request-files/?utm_source=chatgpt.com))

---

## **Start processing**

POST /v1/jobs  
{  
  "document\_ids": \[  
    "doc\_123",  
    "doc\_456",  
    "doc\_789"  
  \],  
  "mode": "full"  
}

Response:

202 Accepted  
{  
  "job\_id": "job\_001",  
  "status": "queued"  
}  
---

## **Job status**

GET /v1/jobs/{job\_id}

Response:

{  
  "id": "job\_001",  
  "status": "running",  
  "stage": "fact\_extraction",  
  "progress": 61,  
  "completed\_items": 74,  
  "total\_items": 121  
}  
---

## **List documents**

GET /v1/documents  
---

## **Document detail**

GET /v1/documents/{document\_id}  
---

## **Pages**

GET /v1/documents/{document\_id}/pages  
---

## **Facts**

GET /v1/facts

Query parameters:

document\_id  
entity  
predicate  
validation\_status  
min\_confidence  
page  
limit  
---

## **Individual fact**

GET /v1/facts/{fact\_id}

Returns the fact plus provenance.

---

## **Relationships**

GET /v1/relationships

Parameters:

type  
document\_id  
confidence  
primary\_dimension  
---

## **Individual relationship**

GET /v1/relationships/{relationship\_id}

Returns:

fact A  
evidence A  
fact B  
evidence B  
relationship  
context differences  
explanation  
confidence  
---

## **Summary**

GET /v1/knowledge/summary

Example:

{  
  "documents": 3,  
  "facts": 842,  
  "validated\_facts": 811,  
  "warnings": 21,  
  "rejected": 10,  
  "relationships": 94,  
  "corroborations": 31,  
  "contradictions": 12,  
  "reconciliations": 24,  
  "uncertain": 27  
}  
---

# **23\. I would NOT expose raw embeddings through the API**

They're implementation details.

Don't create:

GET /embeddings

The application only needs:

facts  
relationships  
evidence  
---

# **24\. Processing pipeline in exact order**

This is the pipeline your coding agent should implement.

## **Stage 1 — Ingestion**

upload PDF  
 ↓  
SHA-256  
 ↓  
create document  
 ↓  
save original

## **Stage 2 — PDF decomposition**

PDF  
 ↓  
pages  
 ↓  
text blocks  
 ↓  
tables  
 ↓  
coordinates

PyMuPDF is particularly suitable because its text extraction exposes pages/blocks/coordinates and table extraction through `find_tables()`. ([PyMuPDF](https://pymupdf.readthedocs.io/en/latest/app1.html?utm_source=chatgpt.com))

## **Stage 3 — Cleanup**

Detect:

headers  
footers  
page numbers  
repeated boilerplate

Do not accidentally remove meaningful repeated text.

## **Stage 4 — Page quality analysis**

Determine:

good text  
low text  
scanned

Only invoke OCR / visual fallback where necessary.

## **Stage 5 — Chunk generation**

Create:

semantic chunks

with:

pages  
blocks  
heading path  
text

## **Stage 6 — Extraction**

Parallel structured calls.

chunk 1 ─┐  
chunk 2 ─┤  
chunk 3 ─┤──→ extraction workers  
...

with concurrency cap.

## **Stage 7 — Validation**

Verify:

schema valid  
quote exists  
page exists  
fact values sane

## **Stage 8 — Normalization**

Run deterministic logic:

numbers  
currency  
units  
percentages  
dates

## **Stage 9 — Entity/predicate normalization**

Create canonical representations.

## **Stage 10 — Deduplication**

Within each document:

duplicate facts

are merged.

But preserve all evidence locations.

This matters because the same fact may legitimately appear multiple times.

## **Stage 11 — Embedding**

Generate embedding for:

canonical subject  
\+  
canonical predicate  
\+  
value/context summary

For example:

"Company X | revenue | FY2025 | consolidated | USD"

rather than just:

"8.2 billion"

## **Stage 12 — Candidate generation**

Use:

entity similarity  
predicate similarity  
time compatibility  
scope compatibility  
embedding similarity

## **Stage 13 — Relationship reasoning**

Only plausible candidate pairs get the LLM.

## **Stage 14 — Relationship validation**

Check:

does the relationship explanation refer to actual differences?  
does the evidence belong to these facts?  
is the classification consistent with structured context?

## **Stage 15 — Store and surface**

Everything is persisted.

---

# **25\. The extraction prompt**

The extraction prompt should be intentionally conservative.

It should **not** ask the model to compare facts.

Its job is only:

> "What factual claims does this piece of the document actually contain?"

I recommend this structure:

## **GLOBAL INSTRUCTION FOR EVERY PHASE**

You are implementing the Superjoin VIT 2026 Engineering Intern assignment: a Fact Knowledge Layer.

The assignment requires:

1. meaningful numerical or semantic fact extraction;  
2. every fact grounded in source-document evidence;  
3. identification of corroboration, contradiction, or contextual reconciliation;  
4. an example of an extraction/reasoning failure and how it is handled;  
5. an API or UI that accepts additional PDFs;  
6. no hard-coded facts, filenames, document schemas, or document-specific rules.

Engineering priorities, in order:

1. correctness and provenance;  
2. explainability;  
3. reliable behavior on unseen PDFs;  
4. simple architecture;  
5. performance;  
6. UI polish.

Do NOT build:

* a graph database as the core system;  
* an autonomous agent swarm;  
* a chatbot-first RAG system;  
* hard-coded rules for the three starter PDFs;  
* a large framework stack unless clearly necessary.

Prefer:

* Python;  
* FastAPI;  
* PyMuPDF;  
* Pydantic;  
* SQLite;  
* structured LLM outputs;  
* asyncio with bounded concurrency;  
* embeddings only for candidate retrieval;  
* deterministic normalization for numbers/dates/units;  
* Streamlit or similarly simple frontend.

Never fabricate source quotes, page numbers, facts, or evidence.

Every factual claim exposed by the application must be traceable to:  
document → page → block/chunk → exact source quote.

Keep raw source wording separate from normalized interpretation.

When implementing a phase:

* inspect the existing repository before modifying it;  
* preserve working behavior;  
* make small coherent changes;  
* add tests for new behavior;  
* run the tests;  
* fix failures before finishing;  
* update README/documentation where architecture changes;  
* do not silently introduce unnecessary dependencies.

---

# **PHASE 1 — PROJECT FOUNDATION**

Goal: create the project skeleton and development foundation only.

Build:

fact-knowledge-layer/  
app/  
api/  
core/  
db/  
models/  
services/  
ingestion/  
extraction/  
normalization/  
matching/  
reasoning/  
workers/  
tests/  
data/  
storage/  
ui/  
scripts/

Requirements:

1. Python project using pyproject.toml.  
2. FastAPI application.  
3. Pydantic models.  
4. SQLite database.  
5. configuration through environment variables.  
6. .env.example, never commit secrets.  
7. logging configuration.  
8. pytest setup.  
9. /health endpoint.  
10. clean application entrypoint.  
11. README with setup instructions.  
12. create useful Git commits after completing the phase.

Environment variables must include configurable values for:

* OPENAI\_API\_KEY  
* EXTRACTION\_MODEL  
* RELATIONSHIP\_MODEL  
* EMBEDDING\_MODEL  
* STORAGE\_DIR  
* DATABASE\_URL  
* MAX\_LLM\_CONCURRENCY  
* MAX\_FILE\_SIZE\_MB

Do not implement extraction yet.

Before finishing:

* run the application;  
* call /health;  
* run tests;  
* verify a clean clone can install dependencies.

---

# **PHASE 2 — DATABASE AND DOMAIN MODELS**

Implement the complete data model.

Create Pydantic models and SQLAlchemy/SQLite persistence models for:

Document  
Page  
Block  
Chunk  
Fact  
Entity  
EntityAlias  
FactEmbedding  
CandidatePair  
Relationship  
Job  
LLMCache

Important constraints:

FACTS MUST BE GENERIC.

Do not create document-specific fields such as revenue, CEO, employee\_count, etc.

Fact must support:

* subject  
* predicate  
* raw value  
* value type  
* numeric value  
* normalized value  
* unit  
* currency  
* temporal context  
* scope  
* geography  
* qualifiers  
* source quote  
* source page(s)  
* source block IDs  
* extraction confidence  
* validation state  
* notes

Relationship must support:

* fact A  
* fact B  
* relationship type:  
  corroborates  
  contradicts  
  reconciles  
  uncertain  
  unrelated  
* confidence  
* primary difference dimension  
* structured context comparison  
* explanation  
* evidence references  
* reasoning version

Implement database indexes for:

* document\_id  
* page number  
* fact subject/entity  
* fact predicate  
* relationship type  
* candidate status  
* content hashes

Use SQLite JSON support for flexible metadata where appropriate rather than creating dozens of sparse columns. SQLite currently supports JSON functions/operators.

Add database initialization and migrations/schema creation.

Add tests for:

* model validation;  
* database round trips;  
* foreign-key relationships;  
* serialization/deserialization.

Do not implement LLM logic yet.

---

# **PHASE 3 — PDF INGESTION AND LAYOUT PRESERVATION**

Implement PDF processing using PyMuPDF.

Requirements:

1. Accept PDF only.  
2. Calculate SHA-256 before processing.  
3. Reject duplicate documents by hash unless explicitly reprocessed.  
4. Save uploaded PDF to STORAGE\_DIR.  
5. Extract every page.  
6. Store raw page text.  
7. Store cleaned page text separately.  
8. Extract text blocks with bounding boxes.  
9. Preserve reading order.  
10. Detect headings where reasonably possible.  
11. Detect tables using PyMuPDF's table functionality.  
12. Preserve table content and bounding boxes.  
13. Detect low-text/scanned pages.  
14. Add an OCR fallback abstraction, but do not OCR every page automatically.  
15. Remove repeated headers/footers conservatively.  
16. Never discard the original raw page text.  
17. Preserve page numbers exactly as PDF page indices beginning at 1\.

Create:

DocumentIngestor  
PageExtractor  
BlockExtractor  
TableExtractor  
HeaderFooterDetector  
PageQualityAnalyzer

Do not make the LLM responsible for PDF parsing.

Add a fixture PDF test if possible.

Add tests for:

* page count;  
* block extraction;  
* coordinates;  
* duplicate detection;  
* low-text detection.

Document the extraction architecture in README.

---

# **PHASE 4 — CHUNKING**

Implement page-aware, layout-aware chunking.

Do NOT chunk by fixed number of pages alone.

Use:

* headings;  
* paragraphs;  
* table blocks;  
* natural section boundaries;  
* token count.

Target approximately 1,000–2,500 tokens per chunk, but allow smaller chunks for naturally small sections and larger chunks where splitting would destroy meaning.

Each chunk must contain:

* document\_id  
* sequence\_index  
* start\_page  
* end\_page  
* block\_ids  
* heading\_path  
* text  
* token\_count  
* hash  
* previous\_chunk\_id  
* next\_chunk\_id

Allow small contextual overlap between neighboring chunks.

Important provenance rule:

A fact extracted from a chunk may only cite source blocks that actually belong to that chunk.

Create a CLI:

python \-m app.cli.chunk DOCUMENT\_ID

Add tests for:

* chunk ordering;  
* page boundaries;  
* table preservation;  
* overlap;  
* deterministic chunk hashes.

---

# **PHASE 5 — STRUCTURED LLM FACT EXTRACTION**

Implement the extraction service using the OpenAI Python SDK and structured model output with Pydantic.

Use the Responses API / current structured-output facilities rather than manually parsing arbitrary prose JSON.

Create:

* ExtractionResult  
* ExtractedFact  
* ExtractionService  
* PromptVersion

Use a prompt that strictly separates:

1. what the source explicitly states;  
2. normalized interpretation.

Extraction system prompt:

"You extract factual claims from supplied document text.

Only extract facts directly supported by the supplied text.

A fact should be meaningful and potentially useful for cross-document comparison.

Prioritize:

* numerical claims;  
* dates and periods;  
* people and roles;  
* organizations;  
* locations;  
* business metrics;  
* events;  
* quantities;  
* material semantic claims.

For every fact:

* preserve the source wording;  
* identify subject and predicate;  
* preserve values and units;  
* preserve temporal context;  
* preserve scope and qualifiers;  
* provide an exact source quote;  
* do not infer unsupported facts;  
* do not compare this fact with facts from other chunks;  
* do not invent evidence."

The model must return:

* facts;  
* exact source quote;  
* raw subject/predicate;  
* raw value;  
* temporal information;  
* scope;  
* qualifiers;  
* confidence.

CRITICAL:  
The model MUST NOT invent page numbers. Page information comes from the application and is attached to the result based on the chunk metadata.

For every extracted fact:

* validate against Pydantic;  
* verify source\_quote exists in the chunk/page text after normalization;  
* mark invalid evidence as rejected or warning;  
* never silently accept an unsupported citation.

Implement bounded asynchronous concurrency.

Implement retries with exponential backoff for transient failures.

Implement LLM result caching keyed by:  
document/chunk hash

* prompt version  
* model  
* operation.

Do not use OpenAI Batch for interactive processing.

Add mock-provider tests so the test suite does not require an API key.

---

# **PHASE 6 — NORMALIZATION, ENTITY RESOLUTION, AND DEDUPLICATION**

Implement deterministic normalization first.

Numeric normalization:

* thousands  
* millions  
* billions  
* trillions  
* comma-separated numbers  
* currency symbols  
* currency codes  
* percentages  
* ratios where safely parseable

Date normalization:

* years  
* quarters  
* fiscal years  
* month/year  
* explicit date ranges

Do NOT infer exact fiscal-year boundaries unless supported by document context.

Implement canonical entities:

* organization  
* person  
* location  
* product  
* other

Preserve aliases.

Implement predicate normalization but NEVER force low-confidence synonym equivalence.

For example:  
"revenue" and "sales" may be related but are not automatically identical.

Implement same-document fact deduplication.

Deduplication must preserve all source evidence locations.

Do not merge facts merely because values are equal.

Two identical values can refer to different:

* periods;  
* scopes;  
* geographies;  
* metrics.

Create tests for:

* 1.2 billion \== 1,200 million;  
* 2.5% normalization;  
* FY2025 preservation;  
* duplicate facts with different periods not merging;  
* duplicate facts with equivalent evidence merging;  
* uncertain entity matches remaining uncertain.

---

# **PHASE 7 — EMBEDDINGS AND CANDIDATE GENERATION**

Implement semantic candidate retrieval.

Use embeddings only for finding plausible fact pairs.

Do NOT let embeddings determine corroboration or contradiction.

Embed a canonical representation containing:

* canonical subject/entity;  
* predicate;  
* value type;  
* relevant temporal context;  
* scope;  
* geography;  
* qualifiers.

Store embeddings in SQLite as binary/serialized vectors.

Use text-embedding-3-small by default unless an environment variable specifies another compatible model.

Create candidate generation pipeline:

1. exclude same fact;  
2. prefer cross-document comparisons;  
3. reject clearly incompatible entity types;  
4. perform entity similarity;  
5. perform predicate similarity;  
6. check unit compatibility;  
7. check temporal compatibility;  
8. check scope compatibility;  
9. use embedding similarity;  
10. assign candidate score;  
11. retain top candidates above configurable threshold.

Candidate generation must remain conservative.

Store WHY a candidate was selected.

Example:  
\[  
"same canonical entity",  
"predicate semantic similarity 0.91",  
"same fiscal year",  
"embedding similarity 0.88"  
\]

Do not call the relationship LLM yet.

Add tests with synthetic facts.

---

# **PHASE 8 — HYBRID RELATIONSHIP ENGINE**

Implement a hybrid relationship classifier.

First run deterministic comparison.

Compare:

* entity;  
* predicate;  
* numeric values;  
* units;  
* dates;  
* periods;  
* geography;  
* scope;  
* qualifiers.

Then call the LLM only for unresolved semantic judgment.

Relationship labels:

CORROBORATES  
CONTRADICTS  
RECONCILES  
UNCERTAIN  
UNRELATED

Important rule:

DIFFERENT VALUES ARE NOT AUTOMATICALLY CONTRADICTIONS.

For contradiction, the facts should normally refer to:

* the same entity;  
* the same or genuinely equivalent predicate;  
* compatible units;  
* compatible period;  
* compatible scope;  
* compatible geography;  
* compatible definition.

For reconciliation:

* values may differ;  
* but a contextual dimension such as time, scope, unit, geography, definition, or qualifier explains the difference.

LLM relationship prompt:

"You are a fact relationship verifier.

You are given two independently extracted facts and their source evidence.

Classify only one:  
CORROBORATES  
CONTRADICTS  
RECONCILES  
UNCERTAIN  
UNRELATED

Do not call two facts contradictory merely because their values differ.

Examine:

1. entity identity;  
2. predicate/metric equivalence;  
3. numerical values;  
4. units/currency;  
5. reporting period;  
6. scope;  
7. geography;  
8. definition;  
9. qualifiers.

A relationship must be justified only using supplied fact data and source evidence.

Do not introduce facts not present in the inputs.

Return a short evidence-based explanation suitable for a user interface.

Also identify the primary dimension responsible for the relationship:  
value, time, scope, unit, entity, definition, geography, other."

The LLM must return structured output.

Do not expose hidden chain-of-thought.

Return only a concise explanation of observable evidence and the decision.

Add relationship confidence and uncertainty.

Cache relationship evaluations.

---

# **PHASE 9 — FASTAPI**

Implement these exact endpoints.

GET /health

POST /v1/documents

POST /v1/jobs

GET /v1/jobs/{job\_id}

GET /v1/documents

GET /v1/documents/{document\_id}

GET /v1/documents/{document\_id}/pages

GET /v1/facts

GET /v1/facts/{fact\_id}

GET /v1/relationships

GET /v1/relationships/{relationship\_id}

GET /v1/knowledge/summary

POST /v1/reprocess/{document\_id}

POST /v1/reprocess/{job\_id}

Requirements:

* correct HTTP status codes;  
* Pydantic request/response schemas;  
* pagination where appropriate;  
* filters for facts and relationships;  
* useful validation errors;  
* OpenAPI documentation.

POST /v1/documents must support multiple PDF files.

POST /v1/jobs must return 202 Accepted and a job ID.

Processing must happen asynchronously.

Implement a lightweight local job runner suitable for a single-machine prototype.

Do not introduce Redis/Celery/RabbitMQ unless necessary.

Ensure repeated submission of an identical PDF does not unnecessarily redo ingestion.

---

# **PHASE 10 — UI**

Build a simple but polished UI.

Preferred structure:

1. Upload page  
2. Processing progress  
3. Knowledge summary  
4. Facts explorer  
5. Relationships explorer  
6. Relationship detail/evidence view  
7. Failure/uncertainty view

The primary user journey should be:

Upload PDFs  
→ Start processing  
→ See progress  
→ See fact counts  
→ Inspect corroboration  
→ Inspect contradiction  
→ Inspect reconciliation  
→ Inspect failure/uncertainty

Do NOT build a chatbot.

For every relationship card show:

* relationship type;  
* confidence;  
* fact A;  
* document/page;  
* exact evidence;  
* fact B;  
* document/page;  
* exact evidence;  
* concise explanation;  
* contextual dimensions considered.

Make corroborations, contradictions, reconciliations, and uncertainty visually distinguishable.

Include a "Source evidence" expandable section.

Do not show unsupported AI-generated prose as if it came from the document.

---

# **PHASE 11 — TESTING AND FAILURE HANDLING**

Build a small synthetic evaluation dataset.

Include at least:

CASE A — CORROBORATION  
Different wording, equivalent meaning and value.

CASE B — CONTRADICTION  
Same entity/metric/period/scope, genuinely different value.

CASE C — RECONCILIATION  
Different values explained by time/scope/unit.

CASE D — EXTRACTION FAILURE  
Malformed table or ambiguous wording that causes uncertainty or extraction failure.

Test:

* evidence validation;  
* numeric normalization;  
* date normalization;  
* entity ambiguity;  
* candidate generation;  
* relationship classification;  
* cache reuse;  
* duplicate document detection.

Important:  
Do not manipulate production results solely to make the four required demo cases appear.

The demonstration must come from real system behavior against actual documents where possible.

If a real extraction failure exists, document it honestly.

If a test fixture is needed for deterministic validation, label it explicitly as synthetic.

---

# **PHASE 12 — README, DEMO, AND FINAL REVIEW**

README must contain these exact sections required by the assignment:

Setup and Run Instructions  
Video Demo Link  
Approach  
Limitations and Next Steps  
Additional Notes

Also include:

* architecture diagram;  
* data model diagram;  
* processing pipeline;  
* why extraction and relationship reasoning are separated;  
* why SQLite was sufficient;  
* why embeddings are used only for candidate generation;  
* caching approach;  
* failure handling;  
* AI tools used;  
* model configuration;  
* security note about credentials.

Do not commit API keys.

Create:  
.env.example

Run:

* tests;  
* lint/type checks if configured;  
* end-to-end processing;  
* clean-install test.

Create a short demo script under docs/demo-script.md.

The demo MUST visibly show:

1. upload;  
2. extracted fact with evidence;  
3. corroboration;  
4. contradiction;  
5. contextual reconciliation;  
6. extraction/reasoning failure and handling.

Use Git meaningfully:

* commits should represent coherent milestones;  
* avoid one giant final commit.

Final response from this phase should summarize:

* files created;  
* tests executed;  
* known limitations;  
* exact run command.

---

# **26\. The most important coding-agent workflow**

Don't paste all of those prompts into Antigravity simultaneously.

Use this sequence:

Phase 1  
   ↓  
inspect / test  
   ↓  
Phase 2  
   ↓  
inspect / test  
   ↓  
Phase 3  
   ↓  
run on actual PDFs  
   ↓  
Phase 4  
   ↓  
run on actual PDFs  
   ↓  
Phase 5  
   ↓  
inspect extraction quality  
   ↓  
Phase 6  
   ↓  
Phase 7  
   ↓  
Phase 8  
   ↓  
Phase 9  
   ↓  
Phase 10  
   ↓  
Phase 11  
   ↓  
Phase 12

**Do not let the agent build the entire application in one pass.**

The assignment rewards clear engineering decisions and trade-offs.

---

# **27\. One additional "review agent" prompt I'd use**

After Phase 8, stop coding and ask the agent to review its own architecture.

Review the current implementation as a skeptical senior engineer.

Do not add features yet.

Your task is to find architectural and correctness problems.

Review specifically for:

1. Provenance integrity  
* Can any fact be produced without an exact source quote?  
* Can a fabricated page number enter the database?  
* Can a quote be attached to the wrong page/chunk?  
* Can normalized facts lose their raw source wording?  
2. PDF robustness  
* What happens with tables?  
* What happens with repeated headers/footers?  
* What happens with scanned pages?  
* What happens when reading order is wrong?  
* What happens when a fact spans two pages?  
3. Extraction reliability  
* Are unsupported claims rejected?  
* Are LLM outputs schema validated?  
* Are retries bounded?  
* Are malformed responses handled?  
* Is the extraction prompt conservative?  
4. Contextual reasoning  
* Can the system mistake different time periods for contradictions?  
* Can different scopes be mistaken for contradictions?  
* Can different currencies/units be compared incorrectly?  
* Can semantically similar but non-equivalent predicates be merged?  
5. Candidate generation  
* Is every fact being compared with every other fact?  
* Are candidate pairs explainable?  
* Are embeddings being used only for retrieval rather than truth judgment?  
6. Caching  
* Does every LLM cache entry include model and prompt version?  
* Will changing a prompt invalidate old results correctly?  
* Can stale extraction results leak into new processing?  
7. Generalization  
* Is any code hard-coded to the three starter documents?  
* Are predicates hard-coded?  
* Are filenames referenced?  
* Are expected facts embedded in production logic?  
8. Failure handling  
* Does the system represent uncertainty rather than forcing a classification?  
* Can extraction failures be surfaced to the UI?  
* Can relationship failures be distinguished from extraction failures?  
9. API  
* Are long-running operations asynchronous?  
* Are correct HTTP status codes used?  
* Is duplicate document processing avoided?  
10. Security  
* Are API keys excluded from source control?  
* Are uploaded filenames sanitized?  
* Are temporary files handled safely?

Produce:  
A. Critical bugs  
B. High-priority risks  
C. Medium-priority improvements  
D. Things that are already good

Do not rewrite the project.

Then recommend the smallest set of changes that materially improves correctness before the demo.

---

# **28\. Then use a targeted debugging prompt**

After running the real 3 PDFs, **don't say "fix everything."**

Use:

I have now processed the three real assignment PDFs.

Do not redesign the system.

Inspect the actual generated:

* documents  
* pages  
* chunks  
* facts  
* candidate pairs  
* relationships  
* logs

Identify the five highest-impact errors or weaknesses.

For each problem provide:

1. what happened;  
2. the exact pipeline stage;  
3. why it happened;  
4. evidence from the stored output;  
5. smallest code change that would fix it;  
6. regression test to add.

Prioritize:

* hallucinated/invalid evidence;  
* missed important facts;  
* incorrect normalization;  
* false contradictions;  
* missed reconciliations;  
* duplicate facts;  
* incorrect entity matching;  
* broken table extraction.

Do not optimize cosmetic UI issues until correctness issues are addressed.

After identifying the five issues, implement fixes one at a time.  
Run regression tests after every fix.  
Do not make changes that are specific only to the starter PDF filenames or exact text.

---

# **29\. Model responsibilities**

This is the conceptual division I'd put directly into the README.

| Task | Deterministic code | LLM |
| ----- | ----- | ----- |
| PDF parsing | ✅ |  |
| Page numbers | ✅ |  |
| Bounding boxes | ✅ |  |
| Header/footer detection | ✅ |  |
| Chunking | ✅ |  |
| Fact discovery |  | ✅ |
| Exact evidence quote |  | ✅ |
| Evidence verification | ✅ |  |
| Number normalization | ✅ | optional |
| Unit normalization | ✅ |  |
| Date normalization | ✅ | assisted |
| Entity alias detection |  | ✅ |
| Predicate similarity |  | ✅ |
| Candidate retrieval | ✅ |  |
| Embedding similarity | ✅ |  |
| Contradiction determination |  | ✅ |
| Reconciliation determination |  | ✅ |
| Relationship confidence | hybrid | hybrid |
| Storage | ✅ |  |
| API | ✅ |  |
| UI | ✅ |  |

This is the architecture's central idea.

---

# **30\. One subtle improvement: use two LLM "roles"**

You don't necessarily need two different models.

But logically have:

### **Extractor**

"What does this chunk say?"

### **Judge**

"What is the relationship between these already-extracted facts?"

Never let the relationship judge go back and "invent" a different fact.

It gets:

Fact A  
Fact B  
Evidence A  
Evidence B  
normalized context

and nothing else.

This separation makes debugging dramatically easier.

---

# **31\. Do you need RAG?**

Not in the conventional sense.

You are technically doing a form of retrieval for candidate selection, but the core problem isn't:

> "Answer a question from documents."

It is:

> "Construct structured facts from documents and relate them."

So don't call the system a RAG application.

Call it something like:

> **Provenance-First Fact Knowledge Layer**

or:

> **Context-Aware Cross-Document Fact Reasoning System**

That better describes what you've actually built.

---

# **32\. Do you need a vector database?**

No.

For:

3 × \~100 pages

and probably hundreds/thousands of facts, SQLite plus in-memory NumPy similarity is sufficient for the prototype.

If later you have:

100,000+ facts

then a real vector index becomes more attractive.

But the assignment explicitly values understandable engineering over production-scale infrastructure.

---

# **33\. Do you need OCR?**

Only as a fallback.

Your pipeline should do:

Page  
 ↓  
text extraction  
 ↓  
text quality score  
 ↓  
good → normal pipeline  
poor → OCR/visual fallback

Do **not** OCR 300 pages by default.

Similarly, table detection should be attempted before invoking more expensive methods. PyMuPDF currently provides both block extraction and table detection, including table-to-DataFrame workflows. ([PyMuPDF](https://pymupdf.readthedocs.io/en/latest/recipes-text.html?utm_source=chatgpt.com))

---

# **34\. Do you need a message queue?**

Not for this submission.

Use:

FastAPI  
\+  
local job runner  
\+  
SQLite job state

The evaluator is not going to hit your service with 100 simultaneous users.

A real queue such as Celery/RabbitMQ would add setup and failure modes with little benefit here. FastAPI's own docs distinguish lightweight background tasks from heavier distributed workloads. ([FastAPI](https://fastapi.tiangolo.com/tutorial/background-tasks/?utm_source=chatgpt.com))

---

# **35\. Do you need React?**

No.

For 36 hours:

**Streamlit is the sane choice.**

Spend the time on:

evidence  
normalization  
candidate generation  
relationship logic  
failure handling

not frontend infrastructure.

The UI only needs to prove the core experience.

---

# **36\. How I would handle the "four required cases"**

Don't make four fake cards.

Build a relationship view and let the system naturally produce cases.

Then curate the best examples for the demo.

### **Case 1 — corroboration**

same entity  
same predicate  
equivalent value  
same context  
different wording

### **Case 2 — contradiction**

same entity  
same predicate  
same context  
different incompatible value

### **Case 3 — reconciliation**

same/similar entity  
same/similar predicate  
different value  
different time/scope/unit

### **Case 4 — failure**

bad extraction  
ambiguous entity  
broken table  
missing context  
uncertain relationship

The assignment explicitly asks you to show the source evidence and reasoning for the first three, and an extraction/reasoning failure for the fourth.

---

# **37\. Your confidence model**

Don't pretend an LLM's arbitrary `0.91` means mathematically calibrated confidence.

Instead build **evidence-based confidence**.

For example:

Extraction confidence  
    ↓  
evidence verified?        \+25  
numeric parse valid?      \+15  
entity clear?             \+20  
predicate clear?          \+20  
context complete?         \+20

Then normalize to a score.

For relationships:

relationship confidence  
\=  
candidate quality  
\+  
context agreement  
\+  
LLM certainty  
\+  
evidence validity

And expose:

HIGH  
MEDIUM  
LOW

in the UI.

This is more honest.

---

# **38\. Add an explicit "uncertain" path**

This is one of the highest-value design decisions.

Your classifier should be allowed to say:

UNCERTAIN

instead of forcing:

CONTRADICTS

For example:

Fact A:  
"Revenue increased significantly."

Fact B:  
"Revenue was $8B."

There's not enough evidence to assert they are the same underlying claim.

Return:

UNCERTAIN

rather than hallucinating a relationship.

That supports the brief's explicit emphasis on ambiguity and uncertainty.

---

# **39\. How to make the UI evaluator-friendly**

The relationship detail page should look roughly like this:

┌─────────────────────────────────────────────────────┐  
│ RECONCILES                              Confidence 94%│  
├─────────────────────────────────────────────────────┤  
│                                                     │  
│ FACT A                                              │  
│ Revenue \= $12.5B                                    │  
│ FY2025                                              │  
│ Global                                              │  
│                                                     │  
│ Annual Report                                       │  
│ Page 47                                             │  
│ ┌───────────────────────────────────────────────┐   │  
│ │ "Revenue for fiscal year 2025 was $12.5B."  │   │  
│ └───────────────────────────────────────────────┘   │  
│                                                     │  
│                         ↕                           │  
│                                                     │  
│ FACT B                                              │  
│ Revenue \= $3.2B                                     │  
│ Q4 FY2025                                           │  
│ Global                                              │  
│                                                     │  
│ Investor Report                                     │  
│ Page 12                                             │  
│ ┌───────────────────────────────────────────────┐   │  
│ │ "Fourth-quarter revenue reached $3.2B."      │   │  
│ └───────────────────────────────────────────────┘   │  
│                                                     │  
├─────────────────────────────────────────────────────┤  
│ WHY                                                 │  
│                                                     │  
│ Values differ, but the reporting periods differ.    │  
│ Fact A covers FY2025; Fact B covers Q4 FY2025.      │  
│ Therefore the claims are compatible rather than    │  
│ contradictory.                                      │  
│                                                     │  
│ Dimension: TIME                                     │  
└─────────────────────────────────────────────────────┘

That page alone demonstrates a huge portion of the assignment.

---

# **40\. Processing progress**

For 300 pages, expose progress by **stage**, not fake percentage.

For example:

Processing documents

✓ Ingestion                300 / 300 pages  
✓ Layout analysis          300 / 300 pages  
✓ Chunking                 184 chunks  
● Fact extraction           96 / 184 chunks  
○ Normalization             —  
○ Candidate generation      —  
○ Relationship analysis     —

Current:  
Extracting facts from chunk 96

That also helps you debug.

FastAPI's upload system supports multiple uploads through `UploadFile`, which makes a three-document ingestion endpoint straightforward. ([FastAPI](https://fastapi.tiangolo.com/tutorial/request-files/?utm_source=chatgpt.com))

---

# **41\. Important current OpenAI implementation choice**

For structured extraction, use the current OpenAI structured-output APIs rather than manually extracting JSON from free-form model text. OpenAI's current documentation shows Python/Pydantic structured parsing and `responses.parse`, specifically for converting unstructured text into typed structures. ([OpenAI Platform](https://platform.openai.com/docs/guides/structured-outputs))

For embeddings, `text-embedding-3-small` is currently documented and supports producing vectors for similarity/search use cases. ([OpenAI Platform](https://platform.openai.com/docs/guides/embeddings))

For credentials, use environment variables; OpenAI's current quickstart similarly recommends environment-based API keys rather than embedding credentials in source. ([OpenAI Platform](https://platform.openai.com/docs/quickstart/make-your-first-api-request?utm_source=chatgpt.com))

---

# **42\. What I would actually build within 36 hours**

### **Must-have**

✅ PDF upload  
✅ 100-page PDF ingestion  
✅ page/block provenance  
✅ table extraction  
✅ semantic chunking  
✅ structured fact extraction  
✅ evidence validation  
✅ normalization  
✅ deduplication  
✅ entity/predicate similarity  
✅ candidate generation  
✅ relationship classification  
✅ uncertainty  
✅ FastAPI  
✅ simple UI  
✅ caching  
✅ tests  
✅ README

### **Nice-to-have**

OCR fallback  
source highlighting  
incremental document addition

### **Do not spend time on**

❌ Neo4j  
❌ Kubernetes  
❌ Redis  
❌ Celery  
❌ complex React application  
❌ autonomous agent framework  
❌ fine-tuning  
❌ elaborate authentication  
❌ multi-tenant architecture  
---

# **43\. Recommended implementation order inside Antigravity**

The order matters.

1\. Foundation  
2\. DB models  
3\. PDF parser  
4\. Chunks  
5\. Fact extraction  
6\. Run on the real 300 pages  
7\. Normalize  
8\. Candidate generation  
9\. Relationship engine  
10\. Run against real PDFs again  
11\. API  
12\. UI  
13\. Failure handling  
14\. Tests  
15\. README/demo

**Do not build the UI before you've processed the real PDFs.**

You need to discover what the actual documents are doing to your extractor.

---

# **44\. Git strategy**

The brief explicitly says to use Git meaningfully.

Make commits like:

feat: initialize FastAPI application  
feat: add document and page persistence  
feat: add PDF block and table extraction  
feat: add page-aware chunking  
feat: add structured fact extraction  
feat: add evidence validation  
feat: add fact normalization  
feat: add candidate generation  
feat: add relationship reasoning  
feat: add knowledge API  
feat: add Streamlit interface  
test: add relationship regression cases  
docs: document architecture and limitations

That's much better than:

final  
final2  
final-final  
---

# **45\. One critical thing I would add to the UI: "Why was this compared?"**

For each relationship:

Candidate generation:

✓ Same entity  
✓ Similar predicate  
✓ Same reporting period  
✓ Same geography  
✓ Semantic similarity: 0.91

Then:

Relationship:  
RECONCILES

This lets the evaluator see that the system didn't randomly throw pairs at an LLM.

That's directly connected to your "discovered, grounded, compared, explained" story.

---

# **46\. Your README architecture section should essentially tell this story**

> The system separates factual extraction from cross-document reasoning. PDFs are first decomposed into page- and block-aware structures so provenance survives the entire pipeline. An LLM extracts candidate facts using a strict structured schema, while the application validates every source quote against the original text. Deterministic normalization handles values, units and dates. Embeddings and metadata are then used to identify plausible cross-document fact pairs. A second reasoning stage classifies those pairs as corroborating, contradicting, reconcilable, uncertain or unrelated, with the decision grounded in the two facts' evidence and contextual dimensions.

That is a much stronger engineering narrative than:

> "We upload PDFs to GPT and use a vector database."

---

# **47\. The biggest risks and how this architecture handles them**

| Risk | Mitigation |
| ----- | ----- |
| Hallucinated facts | conservative extraction \+ evidence validation |
| Fake citations | verify quote against page text |
| Wrong reading order | block/layout extraction |
| Broken tables | explicit table extraction |
| Duplicate facts | deduplication after normalization |
| False contradiction | context-aware hybrid reasoning |
| Semantic synonyms missed | embeddings |
| Embeddings produce false matches | LLM verification |
| Expensive comparison | candidate generation |
| Long processing request | async jobs |
| Repeated API costs | caching |
| Prompt iteration | versioned caches |
| Unseen PDFs fail | generic fact schema |
| Ambiguous claims forced into categories | UNCERTAIN |
| Time pressure | incremental phases \+ coding agent |
| UI consumes too much time | Streamlit/simple frontend |

---

# **48\. Final architectural recommendation**

If I were doing this assignment myself, the final technology stack would be:

                   APPLICATION  
────────────────────────────────────────────

Python 3.x  
FastAPI  
Pydantic  
SQLite  
PyMuPDF  
NumPy  
OpenAI Python SDK  
Streamlit  
pytest

                    AI  
────────────────────────────────────────────

LLM \#1  
Structured Fact Extraction

LLM \#2 / same model  
Relationship Verification

Embedding model  
Semantic Candidate Retrieval

                    STORAGE  
────────────────────────────────────────────

SQLite  
 ├── structured facts  
 ├── provenance  
 ├── jobs  
 ├── relationships  
 ├── cache  
 └── embeddings

Filesystem  
 └── original PDFs

And the conceptual architecture is:

               DOCUMENTS  
                    │  
                    ▼  
              PDF STRUCTURE  
                    │  
          page / block / table  
                    │  
                    ▼  
              SMART CHUNKS  
                    │  
                    ▼  
          STRUCTURED EXTRACTION  
                    │  
                    ▼  
        EVIDENCE-VALIDATED FACTS  
                    │  
                    ▼  
          NORMALIZED FACT LAYER  
                    │  
          ┌─────────┴─────────┐  
          │                   │  
      lexical             embeddings  
      matching             similarity  
          │                   │  
          └─────────┬─────────┘  
                    ▼  
             CANDIDATE PAIRS  
                    │  
                    ▼  
         CONTEXT COMPARISON  
                    │  
                    ▼  
         RELATIONSHIP JUDGE  
                    │  
       ┌────────────┼─────────────┐  
       ▼            ▼             ▼  
  CORROBORATE   CONTRADICT    RECONCILE  
                    │  
                    ▼  
                UNCERTAIN  
                    │  
                    ▼  
           EVIDENCE \+ EXPLANATION  
                    │  
                    ▼  
              API / UI

This is the architecture I would consider **the sweet spot**: technically credible, explainable, generalized beyond the supplied PDFs, capable of handling \~300 pages, and still realistic to implement with a coding agent in 1.5 days.

Most importantly, it directly targets what the brief says they care about: grounded facts, sensible treatment of ambiguity, generalization to new documents, and clear engineering trade-offs.

And the submission requirements are all covered: runnable project, additional-PDF ingestion, facts \+ source evidence \+ cross-document relationships, the four cases, README, AI-tool disclosure, and a ≤3-minute demo.

**One strategic recommendation:** do not start Antigravity by asking it to "build the assignment." Start with **Phase 1, then Phase 2, then Phase 3**, and after Phase 5 run the real three PDFs before allowing it to continue. That feedback point is where you'll discover the document-specific failure modes without accidentally making the whole architecture document-specific.

