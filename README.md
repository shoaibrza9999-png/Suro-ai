| Item | Value |
| :--- | :--- |
| **Username** | 9 |
| **Password** | 9 |
| **Tryout Link** | [https://h-1--rare80801.replit.app/](https://h-1--rare80801.replit.app/) |

-----------------------------------
Name and School: shoaib - RSM public school.
Date: 1/21/26
Project Name: CalorieAI
Description: Turn you boaring study in interactive flashcards,charts,etc by Ai agent.
-----------------------------------

# 🎓 AI Learning Platform: System Architecture

A sophisticated, state-based AI tutoring system designed for personalized education, featuring real-time interaction and deep learning analytics.


---

## 🏗️ Core Components

### 👤 User Management (`database.py`)
The foundation of the personalized experience.
* **Authentication:** Secure registration and login and store in localstorage of user for easy future login.
* **Budgeting:** Granular token usage tracking to manage API overhead and costs.

### 💬 Chat System (`server.py`)
The primary interface for student interaction.
* **Dual Modes:** Dedicated **Study Mode** (guided learning) and **Test Mode** (active recall).
* **Persistence:** Thread-based conversation history for seamless context retention.


### 🧠 LLM Pipeline (`llm.py`)
A robust, state-based workflow utilizing a 4-node architecture:
1.  **Format:** Pre-processes input and structures the initial state.
2.  **Agent:** The central brain determining the best pedagogical approach.
3.  **Tools:** Dynamic execution of external functions (Flashcards, MCQs, etc.).
4.  **Finalize:** Polishes the output for the user and updates the history.

---

## 🛠️ Advanced Learning Features

| Feature | Description |
| :--- | :--- |
| **📄 PDF Analysis** | Extract and synthesize content from uploaded documents for contextual study. |
| **🃏 Flashcards** | AI-generated digital cards optimized for spaced repetition. |
| **📝 MCQ Generation** | Automated multiple-choice questions for instant self-assessment. |
| **📊 Mermaid Diagrams** | Visual learning via dynamically generated flowcharts and mind maps. |
| **🔊 Voice Output** | It generates voice for learning while doing other work. |

---

## 📈 Notes & Resource Management
* **Personalized Study:** User can upload name ,dates of exam or test and about like weakness , strength.
* **Usage Analytics:** Real-time dashboards for token consumption and API costs.
* **File Management:** Per-conversation file organization to keep learning materials structured.
