import os
import sqlite3
import asyncio
import edge_tts
from typing import TypedDict, List, Optional, Literal
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langgraph.graph import START, END, StateGraph
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import BaseModel, Field
from langchain.tools import tool
import requests
import base64
import time
import json

import datetime
import fitz  # PyMuPDF



VOICE_STYLES = {
    "female-english": "en-US-AriaNeural",
    "male-english": "en-US-ChristopherNeural",
    "female-hindi": "hi-IN-SwaraNeural",
    "male-hindi": "hi-IN-MadhurNeural",
    "female-indian-english": "en-IN-NeerjaNeural",
    "male-indian-english": "en-IN-PrabhatNeural"
}

class State(TypedDict):
    messages: list
    query: str
    username: str
    chat_mode: str
    enabled_tools: list
    voice_style: str
    screen_text: str
    audio_text: str
    flashcards: list
    mcqs: list
    audio_path: str
    tokens_used: int
    user_profile: dict
    user_notes: list
    user_files: list
    chart_image: str
    tool_pending: bool
    flashcards: list
    mcqs: list
    screen_text_override: str

class FlashcardItem(BaseModel):
    question: str = Field(description="The question")
    answer: str = Field(description="The answer")
    hint: Optional[str] = Field(default=None, description="Optional hint")

class MCQItem(BaseModel):
    question: str = Field(description="The question")
    a: str = Field(description="Option A")
    b: str = Field(description="Option B")
    c: str = Field(description="Option C")
    d: str = Field(description="Option D")
    answer: Literal["a", "b", "c", "d"] = Field(description="Correct answer")

class FlashcardResponse(BaseModel):
    screen_text: str = Field(description="Text to display on screen")
    flashcards: List[FlashcardItem] = Field(description="List of flashcards")

class MCQResponse(BaseModel):
    screen_text: str = Field(description="Text to display on screen")
    mcqs: List[MCQItem] = Field(description="List of MCQs")

class VoiceResponse(BaseModel):
    screen_text: str = Field(description="Text to display on screen")
    audio_text: str = Field(description="Text to convert to speech")

def get_model():
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        raise ValueError("GROQ_API_KEY not set")
    return ChatGroq(model="openai/gpt-oss-120b", temperature=0.7, api_key=api_key)



def extract_pdf_content(filepath: str, max_pages: int = 5) -> str:
    try:
        # Open the document
        with fitz.open(filepath) as doc:
            num_pages = len(doc)
            text = ""
            
            # Determine how many pages to read
            pages_to_read = min(num_pages, max_pages)
            
            for i in range(pages_to_read):
                page_text = doc[i].get_text()
                text += page_text if page_text else ""
            
            # If the PDF was longer than max_pages, apply your 1000 char cap
            if num_pages > max_pages:
                text = text[:1000]
            
            return text.strip()
            
    except Exception as e:
        print(f"PDF extraction error: {e}")
        return ""
        
def get_system_prompt(state: State) -> str:
    chat_mode = state.get("chat_mode", "study")
    enabled_tools = state.get("enabled_tools", [])
    user_profile = state.get("user_profile", {})
    user_notes = state.get("user_notes", [])
    user_files = state.get("user_files", [])
    
    now = datetime.datetime.now()
    current_datetime = now.strftime("%Y-%m-%d %H:%M:%S")
    today = now.strftime("%Y-%m-%d")
    
    base = f"""You are a helpful study guide AI assistant. Current date and time: {current_datetime}.
You help students learn by answering questions clearly and educationally. Keep responses focused and helpful. Use examples when appropriate.force student to study not answer any other questions except study

"""
    
    if user_profile:
        name = user_profile.get("display_name") or user_profile.get("username", "Student")
        about = user_profile.get("about", "")
        strengths = user_profile.get("strengths", "")
        weaknesses = user_profile.get("weaknesses", "")
        
        base += f"""

USER DETAILS:
- Name: {name}
- About: {about if about else 'Not specified'}
- Strong subjects: {strengths if strengths else 'Not specified'}
- Needs improvement in: {weaknesses if weaknesses else 'Not specified'}"""
    
    if user_notes:
        upcoming_notes = [n for n in user_notes if n.get("date", "") >= today][:5]
        if upcoming_notes:
            base += "\n\nUPCOMING IMPORTANT DATES:"
            for note in upcoming_notes:
                base += f"\n- {note['date']}: {note['text']}"
    
    if user_files:
        base += "\n\nUSER HAS UPLOADED FILES:"
        for f in user_files[:3]:
            filename = f.get("filename", "")
            filepath = f.get("filepath", "")
            base += f"\n- {filename}"
            
            if filepath and os.path.exists(filepath):
                content = extract_pdf_content(filepath)
                if content:
                    base += f"\n  Content preview: {content[:500]}..."
    
    if chat_mode == "test":
        base += "\n\nYou are in TEST MODE. Generate questions to test the student's knowledge. Be encouraging but accurate."
    
    if "voice" in enabled_tools:
        base += "\n\nVOICE TOOL: Use speak_response tool when user wants audio/voice explanation."
    if "flashcards" in enabled_tools:
        base += "\n\nFLASHCARD TOOL: Create flashcards when asked or when it helps learning."
    if "mcqs" in enabled_tools:
        base += "\n\nMCQ TOOL: Generate multiple choice questions when asked."
    if "pdf" in enabled_tools:
        base += "\n\nPDF TOOL: Use summarize_pdf tool to query or summarize uploaded PDFs."
    if "chart" in enabled_tools:
        base += "\n\nCHART TOOL: Use generate_chart tool to create diagrams. The chart will be displayed as an image to the user."
    
    return base

@tool
def generate_chart(chart_code: str) -> str:
    """Renders a Mermaid.js diagram and returns it as a displayable image.
    Args:
        chart_code: Valid Mermaid.js syntax string for the diagram
    """
    clean_code = chart_code.replace("```mermaid", "").replace("```", "").strip()
    graphbytes = clean_code.encode("utf8")
    base64_bytes = base64.b64encode(graphbytes)
    base64_string = base64_bytes.decode("ascii")
    
    url = "https://mermaid.ink/img/" + base64_string + "?bgColor=!white"
    response = requests.get(url)
    
    if response.status_code == 200:
        content_type = response.headers.get('Content-Type', '')
        if 'image' not in content_type:
            return "Error: Could not generate diagram image"
        
        img_base64 = base64.b64encode(response.content).decode('utf-8')
        return f"CHART_IMAGE:data:image/png;base64,{img_base64}"
    else:
        return f"Error: Failed to generate diagram (status {response.status_code})"




@tool
def summarize_pdf_tool(filename: str, prompt: str) -> str:
    """Summarize or answer questions about a specific uploaded PDF file using PyMuPDF."""
    uploads_dir = "uploads"
    filepath = None
    
    # Locate the file
    if os.path.exists(uploads_dir):
        for f in os.listdir(uploads_dir):
            if filename.lower() in f.lower() and f.endswith('.pdf'):
                filepath = os.path.join(uploads_dir, f)
                break
    
    if not filepath or not os.path.exists(filepath):
        return f"Could not find PDF file: {filename}"
    
    try:
        model = get_model()
        
        # Use 'with' to ensure the document is handled properly
        with fitz.open(filepath) as doc:
            total_pages = len(doc)
            
            # --- Scenario A: Short PDF (< 10 pages) ---
            if total_pages < 10:
                text = ""
                for page in doc:
                    text += page.get_text() or ""
                
                if not text.strip():
                    return "Could not extract text from PDF."
                
                full_prompt = f"Based on the following PDF content, {prompt}\n\nPDF CONTENT:\n{text[:8000]}"
                response = model.invoke([HumanMessage(content=full_prompt)])
                return response.content

            # --- Scenario B: Long PDF (>= 10 pages) ---
            else:
                # Step 1: Initial Summary (First 10 pages)
                initial_text = ""
                for i in range(10):
                    initial_text += doc[i].get_text() or ""
                
                # Truncate initial text to prevent overflow
                initial_text = initial_text[:6000]
                
                initial_prompt = f"Based on the following PDF content (Pages 1-10), create an initial summary/answer for: {prompt}\n\nPDF CONTENT:\n{initial_text}"
                
                response = model.invoke([HumanMessage(content=initial_prompt)])
                current_summary = response.content
                
                # Step 2: Iterative Refinement (Next 5-page chunks)
                current_page = 10
                while current_page < total_pages:
                    next_chunk_text = ""
                    end_page = min(current_page + 5, total_pages)
                    
                    for i in range(current_page, end_page):
                        next_chunk_text += doc[i].get_text() or ""
                    
                    if next_chunk_text.strip():
                        # Refine current_summary with the new chunk
                        refine_prompt = (
                            f"USER ORIGINAL INTENT: {prompt}\n\n"
                            f"PREVIOUS SUMMARY: {current_summary}\n\n"
                            f"NEW CONTENT (Pages {current_page+1} to {end_page}):\n{next_chunk_text[:4000]}\n\n"
                            f"INSTRUCTIONS: Update the previous summary to include relevant info from the new content."
                        )
                        response = model.invoke([HumanMessage(content=refine_prompt)])
                        current_summary = response.content
                    
                    current_page += 5
                
                return current_summary
                
    except Exception as e:
        # This will help you see the exact error in the logs
        print(f"Detailed Debug Error: {e}")
        return f"Error processing PDF: {str(e)}"
        

@tool  
def speak_response(text: str) -> str:
    """Convert text to speech audio for the user.
    Args:
        text: The text to convert to speech
    """
    return f"VOICE_OUTPUT:{text}"

@tool
def generate_flashcards(screen_text: str, flashcards: List[FlashcardItem]) -> str:
    """Display a set of flashcards for the user.
    Args:
        screen_text: Text to display on screen alongside the flashcards
        flashcards: A list of flashcard objects, each with a question, answer, and optional hint
    """
    cards_data = []
    for c in flashcards:
        cards_data.append({
            "question": c.question,
            "answer": c.answer,
            "hint": c.hint
        })
    return f"FLASHCARDS:{json.dumps({'screen_text': screen_text, 'flashcards': cards_data})}"

@tool
def generate_mcqs(screen_text: str, mcqs: List[MCQItem]) -> str:
    """Display multiple choice questions (MCQs) for the user.
    Args:
        screen_text: Text to display on screen alongside the MCQs
        mcqs: A list of MCQ objects, each with a question, options (a, b, c, d), and the correct answer
    """
    mcqs_data = []
    for m in mcqs:
        mcqs_data.append({
            "question": m.question,
            "a": m.a,
            "b": m.b,
            "c": m.c,
            "d": m.d,
            "answer": m.answer
        })
    return f"MCQS:{json.dumps({'screen_text': screen_text, 'mcqs': mcqs_data})}"

ALL_TOOLS = [summarize_pdf_tool, speak_response, generate_chart, generate_flashcards, generate_mcqs]
TOOL_MAP = {t.name: t for t in ALL_TOOLS}

def get_available_tools(enabled_tools: list):
    # PDF tool is now internal and always available
    tools = [summarize_pdf_tool]
    if "voice" in enabled_tools:
        tools.append(speak_response)
    if "chart" in enabled_tools:
        tools.append(generate_chart)
    if "flashcards" in enabled_tools:
        tools.append(generate_flashcards)
    if "mcqs" in enabled_tools:
        tools.append(generate_mcqs)
    return tools

def should_continue(state: State):
    messages = state.get("messages", [])
    if not messages:
        return "end"
    
    last_message = messages[-1]
    if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        return "tools"
    return "end"

def call_model(state: State):
    messages = state.get("messages", [])
    enabled_tools = state.get("enabled_tools", [])
    
    model = get_model()
    tools = get_available_tools(enabled_tools)
    
    if tools:
        model_with_tools = model.bind_tools(tools)
    else:
        model_with_tools = model
    
    response = model_with_tools.invoke(messages)
    
    tokens_used = 0
    if hasattr(response, 'usage_metadata') and response.usage_metadata:
        tokens_used = response.usage_metadata.get('total_tokens', 0)
    
    return {
        "messages": messages + [response],
        "tokens_used": tokens_used
    }

def call_tools(state: State):
    messages = state.get("messages", [])
    last_message = messages[-1]
    
    tool_results = []
    chart_image = ""
    audio_text = ""
    flashcards = []
    mcqs = []
    screen_text_override = ""
    
    if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        for tool_call in last_message.tool_calls:
            tool_name = tool_call.get("name", "")
            tool_args = tool_call.get("args", {})
            tool_id = tool_call.get("id", "")
            
            if tool_name in TOOL_MAP:
                try:
                    result = TOOL_MAP[tool_name].invoke(tool_args)
                    
                    if result.startswith("CHART_IMAGE:"):
                        chart_image = result.replace("CHART_IMAGE:", "")
                        result = "Chart generated successfully and displayed to user."
                    elif result.startswith("VOICE_OUTPUT:"):
                        audio_text = result.replace("VOICE_OUTPUT:", "")
                        result = "Audio response will be generated for the user."
                    elif result.startswith("FLASHCARDS:"):
                        data = json.loads(result.replace("FLASHCARDS:", ""))
                        flashcards = data.get("flashcards", [])
                        screen_text_override = data.get("screen_text", "")
                        result = "Flashcards generated successfully."
                    elif result.startswith("MCQS:"):
                        data = json.loads(result.replace("MCQS:", ""))
                        mcqs = data.get("mcqs", [])
                        screen_text_override = data.get("screen_text", "")
                        result = "MCQs generated successfully."
                    
                    tool_results.append(ToolMessage(content=result, tool_call_id=tool_id))
                except Exception as e:
                    tool_results.append(ToolMessage(content=f"Error: {str(e)}", tool_call_id=tool_id))
            else:
                tool_results.append(ToolMessage(content=f"Unknown tool: {tool_name}", tool_call_id=tool_id))
    
    return {
        "messages": messages + tool_results,
        "chart_image": chart_image,
        "audio_text": audio_text,
        "flashcards": flashcards,
        "mcqs": mcqs,
        "screen_text_override": screen_text_override
    }


def format_input(state: State):
    messages = state.get("messages") or []
    query = state.get("query", "")
    
    system_prompt = get_system_prompt(state)
    
    if not messages:
        messages = [SystemMessage(content=system_prompt)]
    elif not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=system_prompt)] + messages
    else:
        messages[0] = SystemMessage(content=system_prompt)
    
    if query:
        messages.append(HumanMessage(content=query))
    
    return {
        "messages": messages,
        "screen_text": "",
        "audio_text": "",
        "audio_path": "",
        "flashcards": [],
        "mcqs": [],
        "screen_text_override": "",
        "tokens_used": 0
    }

def finalize_output(state: State):
    messages = state.get("messages", [])
    voice_style = state.get("voice_style", "female-english")
    audio_text = state.get("audio_text", "")
    chart_image = state.get("chart_image", "")
    flashcards = state.get("flashcards", [])
    mcqs = state.get("mcqs", [])
    screen_text_override = state.get("screen_text_override", "")
    
    screen_text = screen_text_override
    if not screen_text:
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                screen_text = msg.content
                break
    
    audio_path = ""
    if audio_text:
        try:
            voice = VOICE_STYLES.get(voice_style, "en-US-AriaNeural")
            output_path = f"audio_{abs(hash(audio_text)) % 100000}.mp3"
            
            async def gen_audio():
                communicate = edge_tts.Communicate(audio_text, voice)
                await communicate.save(output_path)
                return output_path
            
            audio_path = asyncio.run(gen_audio())
        except Exception as e:
            print(f"Audio generation error: {e}")
    
    return {
        "screen_text": screen_text,
        "audio_path": audio_path,
        "chart_image": chart_image,
        "flashcards": flashcards,
        "mcqs": mcqs
    }

workflow = StateGraph(State)

workflow.add_node("format", format_input)
workflow.add_node("agent", call_model)
workflow.add_node("tools", call_tools)
workflow.add_node("finalize", finalize_output)

workflow.add_edge(START, "format")
workflow.add_edge("format", "agent")
workflow.add_conditional_edges(
    "agent",
    should_continue,
    {
        "tools": "tools",
        "end": "finalize"
    }
)
workflow.add_edge("tools", "agent")
workflow.add_edge("finalize", END)

conn = sqlite3.connect("checkpoints.sqlite", check_same_thread=False)
memory = SqliteSaver(conn)
graph = workflow.compile(checkpointer=memory)

def summarize_pdf_full(filepath: str):
    """Summarize a PDF file and return summary with token count."""
    try:
        with open(filepath, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            text = ""
            for page in reader.pages:
                text += page.extract_text() or ""
        
        if not text.strip():
            return "Could not extract text from PDF.", 0
        
        text = text[:8000]
        
        model = get_model()
        prompt = f"Please provide a comprehensive summary of the following document:\n\n{text}"
        
        response = model.invoke([HumanMessage(content=prompt)])
        
        tokens_used = 0
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            tokens_used = response.usage_metadata.get('total_tokens', 0)
        
        return response.content, tokens_used
    except Exception as e:
        print(f"PDF summarization error: {e}")
        return f"Error summarizing PDF: {str(e)}", 0
