import os
from flask import Flask, request, jsonify, render_template, send_file, Response
from flask_cors import CORS
import queue
import threading
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
import google.generativeai as genai
from gtts import gTTS
import json
import io
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email
import time

load_dotenv()
app = Flask(__name__)
CORS(app)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
try:
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    llm_model = genai.GenerativeModel('gemini-2.5-flash')
except Exception as e:
    print(f"Gemini error: {e}")

verified_invite_sender_email = "YOUR EMAIL"
verified_report_sender_email = "YOUR EMAIL"

interviews = {}
results = {}
current_interview_id = 10000000

UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

#Create page
@app.route('/')
def employer_page():
    return render_template('employer.html')

@app.route('/create-interview', methods = ['POST'])
def create_interview():
    global current_interview_id
    data = request.json
    
    questions = data.get('questions')
    traits = data.get('traits')
    employer_email = data.get('employer_email')
    applicant_emails = data.get('applicant_emails')

    if not all([questions, traits, employer_email, applicant_emails]):
        return jsonify({"error": "Missing data"}), 400
    if not isinstance(applicant_emails, list):
        return jsonify({"error": "applicant_emails should be a list"}), 400

    interview_id = str(current_interview_id)
    current_interview_id += 1

    interviews[interview_id] = {"questions": questions, "traits": traits, "employer_email": employer_email}
    results[interview_id] = []
    interview_link = f"http://localhost:5173/session/{interview_id}"
    report_link = f"http://localhost:5173/results/{interview_id}"
    
    loaded_key = os.getenv('SENDGRID_API_KEY')
    sg = SendGridAPIClient(loaded_key) 
    
    for applicant_email in applicant_emails:
        try:
            message = Mail(
                from_email = verified_invite_sender_email, 
                to_emails = applicant_email,
                subject = "You're Invited to an AI Interview!",
                html_content=f"""
                    <h3>Hello,</h3>
                    <p>You have been invited to complete an automated AI interview.</p>
                    <p>Please click the link below to begin:</p>
                    <a href="{interview_link}" style="padding: 12px 22px; background-color: #007bff; color: white; text-decoration: none; border-radius: 5px; font-weight: bold;">
                        Start Your Interview
                    </a>
                    <p>{interview_link}</p>
                    <p>Good luck!</p>
                """,
            )
            message.reply_to = Email(employer_email)
    
            response = sg.send(message)
            print(f"Email sent for {applicant_email}, status code: {response.status_code}")
        except Exception as e:
            print(f"Error sending email for {applicant_email}: {e}") 
            pass 

    print(f"New interview created, ID: {interview_id}")
    return jsonify({"interview_link": interview_link,"report_link": report_link})

def send_report_email(interview_id):
    interview_data = interviews.get(interview_id)
    report_data = results.get(interview_id)
    recipient_email = interview_data.get("employer_email") if interview_data else None

    if not recipient_email or not report_data:
        print(f"Cannot send report for {interview_id}, missing recipient")
        return
    
    total_rating = 0
    count = 0
    if report_data:
        for res in report_data:
            try: 
                total_rating += int(res['evaluation']['rating'])
                count += 1
            except Exception as e:
                pass
    average = round(total_rating / count if count > 0 else 0, 1)

    html_body = f"<h2>Interview Report -- ID: {interview_id}</h2>"
    html_body += f"<p><strong>Overall Average Rating: {average}/10</strong></p><hr>"
    html_body += "<table border='1' cellpadding='10' cellspacing='0' style='border-collapse: collapse; width: 100%;'>"
    html_body += "<thead><tr><th>Question</th><th>Answer</th><th>Rating</th><th>Feedback</th></tr></thead><tbody>"
    for item in report_data:
        q = item.get("question", "N/A")
        a = item.get("answer", "N/A")
        rating = item.get("evaluation", {}).get("rating", "N/A")
        feedback = item.get("evaluation", {}).get("feedback", "N/A")
        html_body += f"<tr><td>{q}</td><td>{a}</td><td>{rating}/10</td><td>{feedback}</td></tr>"
    html_body += "</tbody></table>"

    try:
        message = Mail(
            from_email = verified_report_sender_email,
            to_emails = recipient_email,
            subject = f"Interview Report - ID: {interview_id}",
            html_content = html_body
        )
        print(f"DEBUG: SENDGRID_API_KEY loaded: {SENDGRID_API_KEY is not None}")
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        print(f"Report sent to {recipient_email}")
    except Exception as e:
        print(f"Error sending email for {interview_id} to {recipient_email}: {e}")

@app.route('/interview/<interview_id>')
def interview_page(interview_id):
    if interview_id not in interviews:
        return "Interview not found", 404
    return render_template('interview.html', interview_id = interview_id)

@app.route('/get-questions/<interview_id>')
def get_questions(interview_id):
    interview_data = interviews.get(interview_id)
    if not interview_data:
        return jsonify({"error": "Interview not found"}), 404
    return jsonify({"questions": interview_data.get("questions", [])})

status_updates = {}

def send_status_update(interview_id, status):
    if interview_id in status_updates:
        status_updates[interview_id].put(status)

@app.route('/api/status/<interview_id>')
def status(interview_id):
    def generate():
        q = queue.Queue()
        status_updates[interview_id] = q
        try:
            while True:
                try:
                    status = q.get(timeout=30)
                    yield f"data: {status}\n\n"
                except queue.Empty:
                    yield f"data: ping\n\n"
        finally:
            if interview_id in status_updates:
                del status_updates[interview_id]
    
    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/text-to-speech', methods = ['POST'])
def text_to_speech():
    data = request.json
    text_to_speak = data.get('text')
    if not text_to_speak:
        return jsonify({"error": "No text provided"}), 400
    
    try:
        audio_fp = io.BytesIO()
        tts = gTTS(text = text_to_speak, lang = "en")
        tts.write_to_fp(audio_fp)
        audio_fp.seek(0)
        
        print(f"Generated text audio for : {text_to_speak}")
        response = send_file(
            audio_fp, 
            mimetype = "audio/mpeg",
            as_attachment = False,
            download_name = "question.mp3"
        )
        response.headers['Accept-Ranges'] = 'bytes'
        return response
    except Exception as e:
        print(f"Error in gTTS: {e}")
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/upload', methods = ['POST'])
def upload_audio_and_evaluate():

    file = request.files.get('file')
    if not file:
        return jsonify({"error": "no file part"}), 400
    question = request.form.get('questionText')
    interview_id = request.form.get('interviewId')
    if not interview_id:
        interview_id = request.form.get('sessionId')

    if not all([file, question, interview_id]):
         return jsonify({"error": "Missing file, questionText, or interviewId"}), 400

    base_dir = os.path.dirname(os.path.abspath(__file__))
    uploads_dir = os.path.join(base_dir, 'uploads')
    os.makedirs(uploads_dir, exist_ok=True)

    original_name = file.filename or ''
    safe_name = secure_filename(original_name) if original_name else None
    if not safe_name:
        ts = time.strftime('%Y%m%d-%H%M%S')
        safe_name = f'recording-{ts}.webm'

    save_path = os.path.join(uploads_dir, safe_name)
    print(f"Attempting to save file to: {save_path}")
    
    try:
        file.save(save_path)
    except Exception as e:
        print(f"Failed to save uploaded file to {save_path}: {e}")
        return jsonify({"error": f"failed to save file: {str(e)}"}), 500
    
    if not os.path.exists(save_path) or os.path.getsize(save_path) < 1000:
        return jsonify({"error": "Uploaded audio file is empty or corrupted"}), 400
    try:
        send_status_update(interview_id, json.dumps({
            "status": "Uploading to Gemini AI",
            "step": 1,
            "total_steps": 4
        }))
        print(f"Uploading file to Gemini: {save_path}")
        audio_gemini = genai.upload_file(path=save_path, mime_type="audio/webm")
        print("File uploaded to Gemini successfully")
        
        send_status_update(interview_id, json.dumps({
            "status": "Processing audio file",
            "step": 2,
            "total_steps": 4
        }))
        
        for attempt in range(10):
            time.sleep(2)
            audio_gemini = genai.get_file(audio_gemini.name)
            send_status_update(interview_id, json.dumps({
                "status": f"Processing audio file (attempt {attempt + 1}/10)",
                "step": 2,
                "total_steps": 4
            }))
            if audio_gemini.state.name == "ACTIVE":
                print("✅ Gemini file ACTIVE")
                break
            elif audio_gemini.state.name == "FAILED":
                raise ValueError("Gemini upload failed: file processing failed.")
        else:
            raise TimeoutError("Gemini file did not become ACTIVE in time.")

        prompt = """Please transcribe the audio file. 
        Instructions:
        1. Listen to the audio carefully
        2. Transcribe all spoken words
        3. Return only the transcription text
        4. If no speech is detected, return 'No speech detected'"""
        
        send_status_update(interview_id, json.dumps({
            "status": "Converting speech to text",
            "step": 3,
            "total_steps": 4
        }))
        print("Sending transcription request to Gemini...")
        response = llm_model.generate_content([prompt, audio_gemini])
        
        if not response.candidates or not response.candidates[0].content:
            raise ValueError("No valid response from transcription model")
            
        answer = response.candidates[0].content.parts[0].text.strip()
        if not answer:
            answer = "No speech detected"
            
        print(f"Transcription complete: {len(answer)} characters")
        
        try:
            genai.delete_file(audio_gemini.name)
            print("Cleaned up Gemini file")
        except Exception as e:
            print(f"Warning: Failed to delete Gemini file: {e}")
            
        if os.path.exists(save_path):
            os.remove(save_path)
            print("Cleaned up local file")
        print(f"Transcribed audio to : {answer}")

    except (TimeoutError, APIError) as e:
        print(f"File handling error: {e}")
        if 'audio_gemini' in locals() and audio_gemini:
            genai.delete_file(audio_gemini.name)
        if os.path.exists(save_path):
            os.remove(save_path)
        return jsonify({"error": f"File processing failed: {str(e)}"}), 500
    except Exception as e:
        print(f"Error in transcription: {e}")
        if 'audio_gemini' in locals() and audio_gemini:
            genai.delete_file(audio_gemini.name)
        if os.path.exists(save_path):
            os.remove(save_path)
        return jsonify({"error": str(e)}), 500
    
    if not answer:
        answer = "No answer spoken"

    try:
        interview_data = interviews.get(interview_id)
        if not interview_data:
            return jsonify({"error": "Interview data not found"}), 404
        
        traits_list = interview_data.get("traits", []) 
        traits_string = ", ".join(traits_list)
        question_list = interview_data.get("questions", [])

        prompt = f"""
        You are a hiring manager looking for these specific traits: {traits_string}.
        
        Evaluate the candidate's answer based *only* on the question and how well it demonstrates those traits.
        
        Provide a rating from 1-10 and a brief justification in the feedback.
        The feedback should *specifically mention* how the answer did or did not reflect the desired traits.

        Return only a valid JSON object in this exact schema:
        {{
            "rating": 8,
            "feedback": "This answer showed good Creativity by..."
        }}

        ---
        Question: "{question}"
        Candidate's answer: "{answer}"
        ---
        """

        print("Sending evaluation request to Gemini...")
        response = llm_model.generate_content(prompt)
        
        if not response.candidates or not response.candidates[0].content:
            raise ValueError("No valid response from evaluation model")

        print(response)
            
        json_text = response.candidates[0].content.parts[0].text.replace("```json", "").replace("```", "").strip()
        print(json_text)
        try:
            evaluation_json = json.loads(json_text)
            print(evaluation_json)
            if not isinstance(evaluation_json, dict) or 'rating' not in evaluation_json or 'feedback' not in evaluation_json:
                raise ValueError("Invalid evaluation format")
        except json.JSONDecodeError as e:
            print("can't parse")
            raise ValueError(f"Failed to parse evaluation response: {e}")
        
        results[interview_id].append({"question": question, "answer": answer, "evaluation": evaluation_json})
        
        print(f"Evaluated Rating: {evaluation_json.get('rating')}/10")

        is_last_question = False
        try:
            current_question_index = question_list.index(question)
            if current_question_index == len(question_list) - 1:
                is_last_question = True
        except ValueError:
            if len(results[interview_id]) == len(question_list):
                is_last_question = True
                print(f"Triggering report for {interview_id}: all questions answered.")
        
        if is_last_question:
            print("Sending final report...")
            send_report_email(interview_id)
        return jsonify(evaluation_json)
    
    except Exception as e:
        print(f"Error in evaluation: {e}")
        return jsonify({"error": "Error evaluating answer"}), 500
    
@app.route('/report/<interview_id>')
def report_page(interview_id):
    if interview_id not in results:
        return "Report not found", 404
    return render_template('report.html', interview_id = interview_id)

@app.route('/get-report-data/<interview_id>', methods = ['GET'])
def get_report_data(interview_id):
    if interview_id not in results:
        return jsonify({"error": "Report not found"}), 404
    
    all_results = results.get(interview_id, [])
    
    total_rating = 0
    count = 0
    if all_results:
        for res in all_results:
            try:
                total_rating += int(res['evaluation']['rating'])
                count += 1
            except Exception:
                pass
    average = total_rating / count if count > 0 else 0
    return jsonify({"results": all_results, "average_rating": round(average, 1)})

if __name__ == "__main__":
    app.run(debug = True, port = 5000)