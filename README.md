# LogLens AI

LogLens AI is an AI-assisted incident investigation platform that helps engineers search technical documentation and investigate recurring system issues more efficiently.

Instead of manually searching through logs, runbooks, PDFs, and other technical files, users can upload documentation into LogLens, search across the available knowledge, and ask questions through an AI-assisted Q&A workflow grounded in retrieved context.

> **Status:** LogLens AI is an independent full-stack prototype currently under development.

---

## The Problem

When a technical incident occurs, engineers may need to search across logs, runbooks, documentation, and previous incident information to understand what happened.

The information needed to investigate an issue can be spread across multiple files and difficult to search quickly.

LogLens AI explores how semantic search and retrieval-augmented generation (RAG) can make that information easier to find and use during an investigation.

---

## What LogLens Does

LogLens currently supports workflows for:

- Uploading and processing technical documents
- Organizing technical information in structured storage
- Searching documents using semantic similarity
- Asking incident-related questions using RAG
- Retrieving relevant context before generating an AI-assisted response
- Managing incident-related information through REST APIs
- Authenticating users and controlling access
- Collecting feedback on generated answers
- Tracking questions and supporting analysis of system usage

---

## How It Works

A simplified LogLens workflow looks like this:

1. **Upload**
   - Technical files are uploaded into the system.

2. **Process**
   - LogLens extracts and prepares the document content.

3. **Store**
   - Structured information is stored using SQLAlchemy-backed database models.

4. **Embed**
   - Document content is converted into vector embeddings.

5. **Retrieve**
   - When a user asks a question, semantic search finds the most relevant document content.

6. **Generate**
   - The retrieved context is used to support an AI-assisted answer through a RAG workflow.

7. **Review**
   - Users can review the response and submit feedback.

### Simplified Architecture

```text
Technical Documents
        |
        v
Document Ingestion
        |
        v
Processing + Storage
        |
        +------------------+
        |                  |
        v                  v
 Structured Data     Vector Embeddings
                           |
                           v
                     Semantic Search
                           |
                           v
                    Relevant Context
                           |
                           v
                       RAG Q&A
                           |
                           v
                        User
                           |
                           v
                       Feedback
