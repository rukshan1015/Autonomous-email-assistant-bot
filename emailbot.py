import os.path
import asyncio
from pydantic import BaseModel, Field
from typing_extensions import TypedDict, Optional
from langchain_core.tools import Tool
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from IPython.display import Markdown, display, Image
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
import base64
import time
from dotenv import load_dotenv

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from email.message import EmailMessage

load_dotenv(override=True)

class EmailContent(BaseModel):
    subject: str = Field(description="Subject line for the reply")
    html_content: str = Field(description="The full HTML reply body")
    is_spam: bool = Field(description="True if the email is junk/marketing")
    is_noreply: bool = Field(description="True if the email is from a noreply address")
    category: str = Field(description="Inquiry, Complaint, Feedback, or Other")


class EmailState(TypedDict):
    sender: str
    email_id: str
    thread_id: str
    raw_body: str
    subject: str
    # Flags - this is to track email status 
    is_spam: bool
    is_noreply: bool
    category: str 
    # Output
    draft: Optional[str] = None
    status: str # ex: "monitored", "drafted", "sent"

## Monitor node

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/gmail.modify']

def get_gmail_service():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('gmail', 'v1', credentials=creds)

def monitor_node(state: EmailState):
    service = get_gmail_service()
    
    # Fetch only the latest 1 unread email
    results = service.users().messages().list(userId='me', q='is:unread', maxResults=10).execute()
    messages = results.get('messages', [])

    if not messages:
        return {"status": "no_new_emails"}

    # Get full message details
    msg = service.users().messages().get(userId='me', id=messages[0]['id']).execute()
    
    # Extract headers (Sender and Subject)
    headers = msg['payload']['headers']
    sender = next(h['value'] for h in headers if h['name'] == 'From')
    subject = next(h['value'] for h in headers if h['name'] == 'Subject')
    
    # Attach to state
    new_state = {
        "email_id": msg['id'],
        "thread_id": msg['threadId'],
        "sender": sender,
        "raw_body": msg['snippet'], # For full body, you'd parse msg['payload']
        "status": "new_email_detected",
        "subject": subject
    }

    return new_state

## Evaluate/Writer node 

def evaluate_write_node(state: EmailState):
  

    llm = ChatOpenAI(model_name="gpt-4o-mini", max_tokens=1000)
    llm_with_structured_output = llm.with_structured_output(EmailContent)

    system_prompt = """
    You are a high-level Executive Assistant for a Physics PhD. Your first task is to 
    triage incoming emails before any response is drafted.

    CRITERIA FOR CLASSIFICATION:
    1. is_spam: Set to True if the email is unsolicited marketing, a newsletter the 
    user didn't sign up for, or suspicious phishing.
    2. is_noreply: Set to True if the sender address is a 'noreply@' address or if 
    the body explicitly states 'Please do not reply to this email'.
    3. category: Assign one of [Inquiry, Complaint, Feedback, Other].

    INSTRUCTIONS:
    - If is_spam or is_noreply is True, keep the 'draft_reply' empty.
    - Otherwise, draft a professional reply in a concise, intellectually rigorous tone.
    - Use clean HTML for the draft body.
    """ 

    user_prompt = f"""
        Email from: {state['sender']}
        Email body: {state['raw_body']}
        """

    response = llm_with_structured_output.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt)
    ])

    return {
        "is_spam": response.is_spam,
        "is_noreply": response.is_noreply,
        "category": response.category,
        "draft": response.html_content,
        "status": "drafted"
    }

## Sender node


def sender_node(state: EmailState):
    # Connecting to Gmail
    service = get_gmail_service()
    
    # Packaging the draft made in the writer node
    mime_msg = EmailMessage()
    mime_msg.set_content(state["draft"], subtype='html') 
    mime_msg['To'] = state['sender']
    mime_msg['Subject'] = "Re: " + state['subject'] 

    raw_bytes = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode()

    # Hitting 'Send' Button
    service.users().messages().send(
        userId='me', 
        body={'raw': raw_bytes, 'threadId': state['thread_id']}
    ).execute()

    # Marking as read.
    service.users().messages().modify(
        userId='me', 
        id=state['email_id'], 
        body={'removeLabelIds': ['UNREAD']}
    ).execute()

    return {"status": "sent"}

# Cleanup node

def cleanup_node(state: EmailState):
    service = get_gmail_service()
    service.users().messages().modify(
        userId='me',
        id=state['email_id'],
        body={'removeLabelIds': ['UNREAD', 'INBOX']}
    ).execute()
    print(f"--- Archived and marked as read: {state.get('subject')} ---")
    return {"status": "archived"}

# Routing functions

def route_after_writer(state: EmailState):

    if state.get('is_spam') or state.get('is_noreply'):
        return "spam/noreply-stop"
    else:
        return "continue"

def email_for_work(state: EmailState):
    if state.get("status") == "no_new_emails":
        return "empty"
    else:
        return "has work"

# Building the graph

graph_builder = StateGraph(EmailState)
graph_builder.add_node("Monitor Emails", monitor_node)
graph_builder.add_node("Evaluate/Write Draft", evaluate_write_node)
graph_builder.add_node("Send Email", sender_node)
graph_builder.add_node("Cleanup", cleanup_node)

graph_builder.add_edge(START, "Monitor Emails")
graph_builder.add_edge("Cleanup", END)

graph_builder.add_conditional_edges("Monitor Emails", email_for_work, {"empty": END, "has work": "Evaluate/Write Draft"})
graph_builder.add_conditional_edges("Evaluate/Write Draft", route_after_writer, {"spam/noreply-stop": "Cleanup", "continue": "Send Email"})

memory = MemorySaver() 

graph = graph_builder.compile(checkpointer=memory)


# Running the graph in a loop

async def main():

    config = {"configurable": {"thread_id": "email_bot_01"}}

    while True:
        try:
            result = await graph.ainvoke({"state": "starting"}, config=config)

            if result.get("status") == "no_new_emails":
                print("No new emails detected.")
            elif result.get("status") == "sent":
                print(f"Replied to: {result.get('sender')}")
            else:
                print(f"Cycle complete with state: {result.get('status')}")
            
        except Exception as e:
            print(f"Error occurred: {e}")

        print("Waiting for 30 seconds before next cycle...")
        await asyncio.sleep(30) # Wait
        
if __name__ == "__main__":
    asyncio.run(main())