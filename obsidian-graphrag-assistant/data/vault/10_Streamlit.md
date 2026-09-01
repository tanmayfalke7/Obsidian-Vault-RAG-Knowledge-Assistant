---
title: Streamlit
tags: [streamlit, frontend, ui, python]
---

# Streamlit

Streamlit is an open-source [[Python]] framework for building interactive web applications from Python scripts. It is used in this project to provide the conversational user interface for the GraphRAG knowledge assistant.

## Key Features

- **Pure Python** — No HTML, CSS, or JavaScript required
- **Reactive** — Reruns on every interaction
- **Fast iteration** — Changes reflect immediately on save
- **Built-in components** — Chat, charts, forms, sidebars

## UI Layout in This Project

### Sidebar
- Knowledge base statistics (notes, chunks, concepts, relationships)
- Graph explorer — enter a concept name to see its graph neighbours
- Refresh statistics button

### Main Area
- Conversational chat interface using `st.chat_message`
- Answer display with markdown rendering
- Sources panel showing retrieved note names
- Graph relationships panel showing concept connections

## Chat Architecture

```
User types question
        ↓
st.chat_input()
        ↓
httpx POST to FastAPI /api/query
        ↓
Display streaming response
        ↓
Show sources + relationships
```

## Why Streamlit?

Streamlit is ideal for this project because:
1. Keeps the frontend thin — all logic is in FastAPI
2. Native Python — matches the rest of the stack
3. Fast to build interactive demos
4. Good support for data display (dataframes, charts)

## Related

- [[Python]] — Streamlit is a Python framework
- [[FastAPI]] — The backend Streamlit communicates with
- [[GraphRAG]] — The capability Streamlit exposes to users
