# Agentic Gmail Assistant 🤖 📧

An automated email management system built with **LangGraph**, **Google Gmail API**, and **OpenAI**. This agent monitors an inbox, categorizes incoming emails, drafts context-aware responses, and manages email states (read/archived) autonomously.

## 🧠 Architecture
The core logic is managed by a stateful graph that ensures reliability and prevents infinite processing loops.
[Graph Architecture](./architecture_graph.png)


### The Workflow:
1. **Monitor Emails**: Polling the Gmail API for `is:unread` messages.
2. **Evaluate/Write**: An LLM analyzes the email to determine if it is spam, a no-reply notification, or a valid inquiry requiring a reply.
3. **Router**: A conditional logic gate that branches based on the LLM's classification.
4. **Send Email**: If valid, the assistant sends a personalized HTML reply.
5. **Cleanup**: A final node that marks the email as `READ` and archives it to prevent duplicate processing.

## 🛠️ Tech Stack
* **Orchestration**: LangGraph (StateGraph).
* **LLM**: OpenAI (GPT-4o / GPT-4o-mini).
* **API**: Google Cloud Console (Gmail API).
* **Environment**: Python (Conda/ai_stable).

## 🚀 Features
- **Idempotency**: Prevents duplicate replies by explicitly managing Gmail `UNREAD` labels.
- **Stateful Management**: Uses a `TypedDict` to pass email metadata, draft content, and status flags across nodes.
- **Spam Filtering**: Automatically archives automated or low-priority emails without human intervention.

## 🔧 Setup & Installation

1. **Enable Gmail API**: Create a project in the [Google Cloud Console](https://console.cloud.google.com/) and download your `credentials.json`.
2. **Install Dependencies**:
   ```bash
   pip install langgraph langchain_openai google-api-python-client google-auth-oauthlib
   ```

3. **Environment Configuration**: 
Configure Environment: Add your OPENAI_API_KEY to your environment variables.

4. **Run the Assistant**:
    ```bash
    python emailbot.py
    ```
## 📝 MIT License

## 🛠️ Key Challenges & Solutions

1. **The "Infinite Reply" Loop**
- **The Problem**: During initial testing, the bot would find an unread email, reply to it, and then find the same email again 30 seconds later, sending hundreds of replies.

- **The Root Cause**: The Gmail API list query was looking for is:unread. While the bot sent the email, it wasn't updating the status of the original message in the inbox.

- **The Solution**: Implemented a dedicated Cleanup Node that explicitly calls service.users().messages().modify to remove the UNREAD and INBOX labels. This ensures "idempotency"—the bot only processes each email exactly once.

2. **State-Router Synchronization**
- **The Problem**: The graph would frequently hang in a "drafted" state without actually sending the email.

- **The Root Cause**: There was a type mismatch between the data the AI was outputting and the TypedDict schema of the EmailState. Specifically, the router couldn't see the "Spam" flags because they weren't being correctly saved to the state.

- **The Solution**: Refined the EmailState to use standardized Python types (str, bool) and added a fallback else path in the conditional router to ensure the graph always has a clear exit strategy.
