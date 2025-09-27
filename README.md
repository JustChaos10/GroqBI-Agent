# GroqBridge for Power BI

An AI agent layer for **Power BI** powered by **Groq**. Ask natural‑language questions about your reports and models, generate insights, and (optionally) run a small server that integrates with your dashboards.

## ✨ Features
- Natural‑language Q&A over Power BI datasets (Groq‑backed inference)
- Server‑integrated mode for embedding/chat experiences
- Utilities for orchestrating Groq requests and formatting answers
- Works alongside your **.pbix** assets (or PBIP projects)

## 📦 Repo contents
```
groq_manager.py
powerbi_agent.py
powerbi_server_integrated.py
*.pbix              # example workbooks (ignored by Git by default)
.env                # secrets (ignored by Git)
```

## 🔧 Requirements
- Python 3.10+
- A Groq API key (environment variable `GROQ_API_KEY`)
- (Optional) Power BI Desktop to edit or create PBIX files

Create a `.env` file:
```
GROQ_API_KEY=your_key_here
```

## 🚀 Setup
```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
# source venv/bin/activate

pip install -r requirements.txt
```

## ▶️ Run
```bash
python powerbi_server_integrated.py   # server-integrated agent
# or
python powerbi_agent.py               # local/CLI agent
```

## 🗂️ Source control notes
- Large **PBIX** files are binary and don’t diff well; they’re ignored by `.gitignore` in this starter.
- Consider **Power BI Projects (PBIP)** for text-based artifacts when appropriate.
- Keep your `.env` out of Git (already ignored).

## 🔐 Security
Store secrets only in environment variables (or secure vaults). Do **not** commit `.env` or credentials.

## 📜 License
If you want *view only / no reuse*, keep the repo with **no open‑source license** and include a custom “All Rights Reserved” file.
