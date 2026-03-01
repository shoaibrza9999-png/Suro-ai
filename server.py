from flask import Flask, render_template, request, jsonify, send_file, Response
from werkzeug.utils import secure_filename
from llm import graph, summarize_pdf_full, get_model
from database import (register_user, verify_user, create_thread_entry, 
                      get_user_threads, update_thread_title, delete_thread_entry,
                      save_message, get_thread_messages, get_user_profile,
                      update_user_profile, add_user_tokens, get_user_notes,
                      add_user_note, delete_user_note, save_uploaded_file, get_user_files,
                      delete_uploaded_file_by_id, get_thread_files)
import uuid
import os
import json

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    if register_user(data['username'], data['password']):
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "User exists"}), 400

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    if verify_user(data['username'], data['password']):
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Invalid credentials"}), 401

@app.route('/api/profile', methods=['POST'])
def get_profile():
    username = request.json.get("username")
    profile = get_user_profile(username)
    if profile:
        profile["cost"] = round((profile["total_tokens"] / 1000000) * 2, 4)
        return jsonify(profile)
    return jsonify({"error": "User not found"}), 404

@app.route('/api/profile/update', methods=['POST'])
def update_profile():
    data = request.json
    update_user_profile(
        data['username'],
        data.get('display_name', ''),
        data.get('about', ''),
        data.get('strengths', ''),
        data.get('weaknesses', '')
    )
    return jsonify({"status": "updated"})

@app.route('/api/notes', methods=['POST'])
def get_notes():
    username = request.json.get("username")
    notes = get_user_notes(username)
    return jsonify(notes)

@app.route('/api/notes/add', methods=['POST'])
def add_note():
    data = request.json
    add_user_note(data['username'], data['date'], data['text'])
    return jsonify({"status": "added"})

@app.route('/api/notes/delete', methods=['POST'])
def delete_note():
    note_id = request.json.get("note_id")
    delete_user_note(note_id)
    return jsonify({"status": "deleted"})

@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file"}), 400
    
    file = request.files['file']
    username = request.form.get('username')
    thread_id = request.form.get('thread_id')
    
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    
    if file and file.filename.endswith('.pdf'):
        filename = secure_filename(file.filename)
        filepath = os.path.join(UPLOAD_FOLDER, f"{username}_{uuid.uuid4().hex[:8]}_{filename}")
        file.save(filepath)
        save_uploaded_file(username, filename, filepath, thread_id)
        return jsonify({"status": "uploaded", "filename": filename, "filepath": filepath})
    
    return jsonify({"error": "Only PDF files allowed"}), 400

@app.route('/api/files/delete', methods=['POST'])
def delete_file():
    file_id = request.json.get("file_id")
    if file_id:
        delete_uploaded_file_by_id(file_id)
        return jsonify({"status": "deleted"})
    return jsonify({"error": "No file_id provided"}), 400

@app.route('/api/files/thread', methods=['POST'])
def get_thread_files_api():
    thread_id = request.json.get("thread_id")
    if thread_id:
        files = get_thread_files(thread_id)
        return jsonify(files)
    return jsonify([])

@app.route('/api/score-test', methods=['POST'])
def score_test():
    data = request.json
    username = data.get("username")
    answers = data.get("answers", [])
    
    if not answers:
        return jsonify({"score": 0, "feedback": "No answers provided"})
    
    try:
        model = get_model()
        
        prompt = """You are a test evaluator. Score the following student answers and provide feedback.

ANSWERS TO EVALUATE:
"""
        for i, ans in enumerate(answers):
            prompt += f"\n{i+1}. Question: {ans.get('question', '')}"
            prompt += f"\n   Correct Answer: {ans.get('correct_answer', '')}"
            prompt += f"\n   Student Answer: {ans.get('user_answer', '')}"
            prompt += f"\n   Type: {ans.get('type', 'text')}\n"
        
        prompt += """

Evaluate each answer and provide:
1. A score out of 100 (be fair but accurate)
2. Brief feedback for each answer
3. Overall feedback

Respond in this exact JSON format:
{"score": <number>, "feedback": "<overall feedback>", "details": [{"correct": true/false, "comment": "<brief comment>"}]}"""

        from langchain_core.messages import HumanMessage
        response = model.invoke([HumanMessage(content=prompt)])
        
        tokens_used = 0
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            tokens_used = response.usage_metadata.get('total_tokens', 0)
        
        add_user_tokens(username, tokens_used)
        
        try:
            content = response.content
            start = content.find('{')
            end = content.rfind('}') + 1
            if start >= 0 and end > start:
                result = json.loads(content[start:end])
                result['tokens_used'] = tokens_used
                return jsonify(result)
        except:
            pass
        
        return jsonify({"score": 50, "feedback": response.content, "tokens_used": tokens_used})
        
    except Exception as e:
        print(f"Scoring error: {e}")
        return jsonify({"score": 0, "feedback": f"Error scoring: {str(e)}"}), 500

@app.route('/api/files', methods=['POST'])
def get_files():
    username = request.json.get("username")
    thread_id = request.json.get("thread_id")
    files = get_user_files(username, thread_id)
    return jsonify(files)

@app.route('/api/chat/stream', methods=['POST'])
def chat_stream():
    data = request.json
    username = data.get("username")
    msg = data.get("message")
    thread_id = data.get("thread_id")
    chat_mode = data.get("chat_mode", "study")
    enabled_tools = data.get("enabled_tools", [])
    
    if not os.environ.get("GROQ_API_KEY"):
        def error_gen():
            yield f"data: {json.dumps({'type': 'error', 'content': 'GROQ_API_KEY not set'})}\n\n"
        return Response(error_gen(), mimetype='text/event-stream')
    
    if not thread_id:
        thread_id = str(uuid.uuid4())
        create_thread_entry(username, thread_id, msg, chat_mode)
        # Link any pending uploaded files to this new thread
        from database import get_conn
        conn = get_conn()
        conn.execute("UPDATE uploaded_files SET thread_id=? WHERE username=? AND thread_id IS NULL", (thread_id, username))
        conn.commit()
        conn.close()
    
    save_message(thread_id, "user", msg)
    
    def generate():
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            import datetime
            
            model = get_model()
            
            now = datetime.datetime.now()
            current_datetime = now.strftime("%Y-%m-%d %H:%M:%S")
            
            system_prompt = f"""You are a helpful study guide AI assistant. Current date and time: {current_datetime}.
You help students learn by answering questions clearly and educationally."""
            
            if chat_mode == "test":
                system_prompt += "\n\nYou are in TEST MODE. Generate questions to test the student's knowledge."
            
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=msg)
            ]
            
            full_response = ""
            for chunk in model.stream(messages):
                if hasattr(chunk, 'content') and chunk.content:
                    full_response += chunk.content
                    yield f"data: {json.dumps({'type': 'chunk', 'content': chunk.content})}\n\n"
            
            tokens_used = len(full_response.split()) * 2
            add_user_tokens(username, tokens_used)
            save_message(thread_id, "ai", full_response, "text", None, None, tokens_used)
            
            yield f"data: {json.dumps({'type': 'done', 'thread_id': thread_id, 'tokens_used': tokens_used})}\n\n"
            
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no'
    })

@app.route('/api/summarize-pdf', methods=['POST'])
def summarize_pdf():
    data = request.json
    filepath = data.get("filepath")
    username = data.get("username")
    
    if not filepath or not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404
    
    try:
        summary, tokens = summarize_pdf_full(filepath)
        add_user_tokens(username, tokens)
        return jsonify({"summary": summary, "tokens_used": tokens})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.json
    username = data.get("username")
    msg = data.get("message")
    thread_id = data.get("thread_id")
    chat_mode = data.get("chat_mode", "study")
    enabled_tools = data.get("enabled_tools", [])
    voice_style = data.get("voice_style", "female-english")
    
    if not os.environ.get("GROQ_API_KEY"):
        return jsonify({
            "response": "Error: GROQ_API_KEY is not set. Please add your Groq API key in the Secrets tab.",
            "thread_id": thread_id or str(uuid.uuid4()),
            "flashcards": [], "mcqs": []
        })
    
    if not thread_id:
        thread_id = str(uuid.uuid4())
        create_thread_entry(username, thread_id, msg, chat_mode)
        # Link any pending uploaded files to this new thread
        from database import get_conn
        conn = get_conn()
        conn.execute("UPDATE uploaded_files SET thread_id=? WHERE username=? AND thread_id IS NULL", (thread_id, username))
        conn.commit()
        conn.close()
    
    save_message(thread_id, "user", msg)
    
    config = {"configurable": {"thread_id": thread_id}}
    
    user_profile = get_user_profile(username) or {}
    user_notes = get_user_notes(username) or []
    user_files = get_thread_files(thread_id) if thread_id else []
    
    try:
        result = graph.invoke({
            "query": msg, 
            "username": username,
            "chat_mode": chat_mode,
            "enabled_tools": enabled_tools,
            "voice_style": voice_style,
            "user_profile": user_profile,
            "user_notes": user_notes,
            "user_files": user_files
        }, config=config)
        
        screen_text = result.get("screen_text", "")
        flashcards = result.get("flashcards", [])
        mcqs = result.get("mcqs", [])
        audio_path = result.get("audio_path", "")
        tokens_used = result.get("tokens_used", 0)
        chart_image = result.get("chart_image", "")
        
        add_user_tokens(username, tokens_used)
        
    except Exception as e:
        print(f"Error in chat: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "response": f"Sorry, there was an error processing your request.",
            "thread_id": thread_id,
            "flashcards": [], "mcqs": []
        })
    
    message_type = "text"
    if flashcards:
        message_type = "flashcards"
    if mcqs:
        message_type = "mcqs"
    if audio_path:
        message_type = "voice"
    if chart_image:
        message_type = "chart"
    
    all_cards = flashcards + mcqs
    save_message(thread_id, "ai", screen_text, message_type, all_cards if all_cards else None, audio_path, tokens_used)
    
    response_data = {
        "response": screen_text,
        "thread_id": thread_id,
        "flashcards": flashcards,
        "mcqs": mcqs,
        "tokens_used": tokens_used
    }
    
    if audio_path and os.path.exists(audio_path):
        response_data["audio_url"] = f"/api/audio/{os.path.basename(audio_path)}"
    
    if chart_image:
        response_data["chart_image"] = chart_image
    
    return jsonify(response_data)

@app.route('/api/audio/<filename>')
def serve_audio(filename):
    if os.path.exists(filename):
        return send_file(filename, mimetype='audio/mpeg')
    return jsonify({"error": "Audio not found"}), 404

@app.route('/api/threads', methods=['POST'])
def get_threads():
    username = request.json.get("username")
    threads = get_user_threads(username)
    return jsonify(threads)

@app.route('/api/threads/delete', methods=['POST'])
def delete_thread():
    tid = request.json.get("thread_id")
    delete_thread_entry(tid)
    return jsonify({"status": "deleted"})

@app.route('/api/threads/rename', methods=['POST'])
def rename_thread():
    data = request.json
    update_thread_title(data['thread_id'], data['new_title'])
    return jsonify({"status": "updated"})

@app.route('/api/history', methods=['POST'])
def get_history():
    thread_id = request.json.get("thread_id")
    messages = get_thread_messages(thread_id)
    
    formatted = []
    for msg in messages:
        entry = {"role": msg["role"], "content": msg["content"], "type": msg.get("type", "text")}
        if msg.get("flashcards"):
            entry["flashcards"] = msg["flashcards"]
        if msg.get("audio_path") and os.path.exists(msg["audio_path"]):
            entry["audio_url"] = f"/api/audio/{os.path.basename(msg['audio_path'])}"
        formatted.append(entry)
    
    return jsonify(formatted)

if __name__ == '__main__':
    import socket
    from werkzeug.serving import run_simple
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(('0.0.0.0', 5000))
        sock.close()
    except:
        pass
    
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)
