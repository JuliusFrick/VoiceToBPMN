# Flask App
from flask import Flask, render_template, request, jsonify
import os
import speech_recognition as sr
from pydub import AudioSegment
import io
import speech_recognition as sr
from pydub import AudioSegment
import io
import json # For parsing JSON from Mistral
from dotenv import load_dotenv
from mistralai.client import MistralClient
from mistralai.models.chat_completion import ChatMessage

load_dotenv() # Load environment variables from .env

app = Flask(__name__)

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
MISTRAL_MODEL_FOR_JSON_GENERATION = os.getenv("MISTRAL_MODEL_FOR_JSON_GENERATION", "mistral-small-latest")
MISTRAL_MODEL_FOR_QUESTIONS = os.getenv("MISTRAL_MODEL_FOR_QUESTIONS", "mistral-small-latest")


mistral_client = None
if MISTRAL_API_KEY and MISTRAL_API_KEY != "YOUR_MISTRAL_API_KEY_HERE":
    mistral_client = MistralClient(api_key=MISTRAL_API_KEY)
else:
    print("Warning: Mistral API key is not configured or is a placeholder. Mistral dependent features will not work.")
    print("Please set your MISTRAL_API_KEY in the .env file.")

# Sanity check for API key (already done by implication above)
if not MISTRAL_API_KEY:
    print("Warning: MISTRAL_API_KEY not found in .env or environment variables.")
elif MISTRAL_API_KEY == "YOUR_MISTRAL_API_KEY_HERE":
    print("Warning: Remember to replace the dummy MISTRAL_API_KEY in .env with your actual key.")


def get_initial_json_from_mistral(text_input):
    if not mistral_client:
        return None, "Mistral client not initialized. Check API key."

    system_prompt = """
You are an expert system designed to convert transcribed audio describing a process into a structured JSON output.
The user will provide a text transcription. Your task is to identify the steps, components, and flow of the process
described and represent it as a JSON object. The JSON should be well-formed.

Example of a desired JSON structure (adapt based on the input text):
{
  "process_name": "Name of the Process",
  "description": "Brief description of the process.",
  "steps": [
    {
      "step_number": 1,
      "action": "Description of the action for this step",
      "details": "Any specific details or sub-actions"
    },
    {
      "step_number": 2,
      "action": "Description of the action for this step",
      "actors": ["Actor1", "Actor2"],
      "dependencies": [1]
    }
  ],
  "inputs": ["Input 1", "Input 2"],
  "outputs": ["Output 1"]
}

Focus on extracting the core process elements. If the text is unclear, make a reasonable interpretation.
Only output the JSON object. Do not include any other text, explanations, or markdown formatting like ```json ... ```.
"""
    try:
        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=f"Here is the transcribed text describing a process:\n\n{text_input}\n\nPlease convert this into a structured JSON object representing the process.")
        ]

        chat_response = mistral_client.chat(
            model=MISTRAL_MODEL_FOR_JSON_GENERATION,
            messages=messages,
            # response_format={"type": "json_object"} # Use if model/API version supports it
        )

        raw_response_content = chat_response.choices[0].message.content
        app.logger.info(f"Raw Mistral response for JSON: {raw_response_content}")

        # Attempt to parse the JSON from the response
        # Mistral might sometimes wrap the JSON in ```json ... ``` or add other text.
        try:
            # Basic cleanup: strip markdown and leading/trailing whitespace
            if raw_response_content.strip().startswith("```json"):
                json_str = raw_response_content.strip()[7:-3].strip()
            elif raw_response_content.strip().startswith("```"): # More generic markdown block
                 json_str = raw_response_content.strip()[3:-3].strip()
            else:
                json_str = raw_response_content.strip()

            parsed_json = json.loads(json_str)
            return parsed_json, None
        except json.JSONDecodeError as e:
            app.logger.error(f"Failed to decode JSON from Mistral response: {e}")
            app.logger.error(f"Problematic JSON string was: {json_str}")
            return None, f"Mistral response was not valid JSON. Raw response: {raw_response_content}"

    except Exception as e:
        app.logger.error(f"Error calling Mistral API for JSON generation: {e}")
        return None, f"Error communicating with Mistral API: {str(e)}"


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/process_audio', methods=['POST'])
def process_audio():
    if 'audio_data' not in request.files:
        return jsonify({"error": "No audio data found", "json_process": None}), 400

    audio_file = request.files['audio_data']

    try:
        audio_data = io.BytesIO(audio_file.read())
        sound = AudioSegment.from_file(audio_data)
        wav_data = io.BytesIO()
        sound.export(wav_data, format="wav")
        wav_data.seek(0)
    except Exception as e:
        app.logger.error(f"Error converting audio: {e}")
        return jsonify({"error": f"Audio conversion failed: {str(e)}. Ensure ffmpeg is installed.", "json_process": None}), 500

    r = sr.Recognizer()
    transcribed_text = ""
    transcription_error = None

    try:
        with sr.AudioFile(wav_data) as source:
            audio_input = r.record(source)
        transcribed_text = r.recognize_google(audio_input)
        app.logger.info(f"Transcription successful: {transcribed_text}")
    except sr.UnknownValueError:
        transcription_error = "Google Web Speech API could not understand audio"
        app.logger.warning(transcription_error)
    except sr.RequestError as e:
        transcription_error = f"Could not request results from Google Web Speech API; {e}"
        app.logger.error(transcription_error)
    except Exception as e:
        transcription_error = f"An unexpected error occurred during transcription: {str(e)}"
        app.logger.error(transcription_error)

    if transcription_error:
        # Still proceed to Mistral if transcription partially failed but got some text?
        # For now, let's return error if transcription itself failed badly.
        # If text is empty but no error, Mistral might handle it (or we add a check).
        return jsonify({"error": transcription_error, "transcribed_text": transcribed_text or None, "json_process": None}), 500

    if not transcribed_text.strip():
        return jsonify({"error": "Transcription resulted in empty text. Cannot generate JSON.", "transcribed_text": "", "json_process": None}), 400

    # Now, call Mistral to get the JSON process
    generated_json, mistral_error = get_initial_json_from_mistral(transcribed_text)

    if mistral_error:
        return jsonify({"error": mistral_error, "transcribed_text": transcribed_text, "json_process": None}), 500

    return jsonify({"transcribed_text": transcribed_text, "json_process": generated_json, "error": None})


def get_refinement_questions_from_mistral(current_json_process_str, conversation_history=None):
    if not mistral_client:
        return None, "Mistral client not initialized. Check API key."

    # Ensure current_json_process_str is a string representation of the JSON
    if not isinstance(current_json_process_str, str):
        current_json_process_str = json.dumps(current_json_process_str, indent=2)

    system_prompt = """
You are an expert system that helps users refine a JSON process description.
The user will provide a JSON object representing a process. Your task is to analyze this JSON
and generate a list of 2-3 specific, actionable questions that would help clarify ambiguities,
add missing details, or improve the overall quality of the process description.

The questions should be directly related to the provided JSON content.
Avoid generic questions. Aim for questions that prompt for concrete information.

Return your questions as a JSON array of strings. For example:
["What is the expected timeframe for step 2?", "Are there any specific tools required for the 'action' in step 3?"]

Only output the JSON array of question strings. Do not include any other text, explanations, or markdown formatting.
"""

    user_content = f"Here is the current JSON process description:\n\n```json\n{current_json_process_str}\n```\n\nPlease provide a few specific questions to help refine it. Remember to return them as a JSON array of strings."

    messages = [
        ChatMessage(role="system", content=system_prompt)
    ]

    # Add conversation history if available (for future iterations)
    if conversation_history:
        for entry in conversation_history: # Assuming history is list of ChatMessage objects
            messages.append(entry)

    messages.append(ChatMessage(role="user", content=user_content))

    try:
        chat_response = mistral_client.chat(
            model=MISTRAL_MODEL_FOR_QUESTIONS,
            messages=messages,
            # response_format={"type": "json_object"} # If supported and we expect a root JSON object
        )

        raw_response_content = chat_response.choices[0].message.content
        app.logger.info(f"Raw Mistral response for questions: {raw_response_content}")

        try:
            # Attempt to directly parse as JSON array
            # Cleanup potential markdown again
            if raw_response_content.strip().startswith("```json"):
                json_str = raw_response_content.strip()[7:-3].strip()
            elif raw_response_content.strip().startswith("```"):
                 json_str = raw_response_content.strip()[3:-3].strip()
            else:
                json_str = raw_response_content.strip()

            questions = json.loads(json_str)
            if isinstance(questions, list) and all(isinstance(q, str) for q in questions):
                return questions, None
            else:
                app.logger.error(f"Mistral response for questions was not a list of strings: {questions}")
                return None, f"Mistral response for questions was not in the expected format (list of strings). Raw: {raw_response_content}"
        except json.JSONDecodeError as e:
            app.logger.error(f"Failed to decode JSON questions from Mistral: {e}")
            # Fallback: try to extract questions if they are simple numbered or bulleted list
            # This is less robust and ideally Mistral follows the JSON array instruction.
            lines = [line.strip() for line in raw_response_content.split('\n') if line.strip()]
            extracted_questions = []
            for line in lines:
                # Remove common list prefixes (e.g., "1. ", "- ", "* ")
                if line.startswith(tuple(f"{i}. " for i in range(1,10))):
                    extracted_questions.append(line[line.find(". ")+2:])
                elif line.startswith(("- ", "* ")):
                    extracted_questions.append(line[2:])
                elif line.endswith("?"): # A simple heuristic
                    extracted_questions.append(line)

            if extracted_questions:
                 app.logger.warning(f"Successfully extracted questions using fallback: {extracted_questions}")
                 return extracted_questions, None

            return None, f"Mistral response for questions was not valid JSON and fallback extraction failed. Raw: {raw_response_content}"

    except Exception as e:
        app.logger.error(f"Error calling Mistral API for questions: {e}")
        return None, f"Error communicating with Mistral API for questions: {str(e)}"


@app.route('/get_refinement_questions', methods=['POST'])
def get_refinement_questions_route():
    data = request.get_json()
    if not data or 'current_json' not in data:
        return jsonify({"error": "Missing 'current_json' in request payload", "questions": None}), 400

    current_json_process = data['current_json']
    # conversation_history = data.get('conversation_history') # For later iterations

    questions, error = get_refinement_questions_from_mistral(current_json_process) #, conversation_history)

    if error:
        return jsonify({"error": error, "questions": None}), 500

    return jsonify({"questions": questions, "error": None})

# Placeholder for the new Mistral interaction function and route
# We'll define MISTRAL_MODEL_FOR_REFINEMENT if needed, or reuse existing.
MISTRAL_MODEL_FOR_REFINEMENT = os.getenv("MISTRAL_MODEL_FOR_REFINEMENT", "mistral-large-latest") # Using a potentially more capable model for complex task

def get_refined_json_and_new_questions(current_json_str, user_answer, conversation_history_list):
    if not mistral_client:
        return None, None, "Mistral client not initialized. Check API key."

    if not isinstance(current_json_str, str):
        current_json_str = json.dumps(current_json_str, indent=2)

    # Construct the conversation history for Mistral
    # The conversation_history_list is expected to be a list of dicts like:
    # [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
    # The last assistant message is the question the user is answering.
    # The user_answer is the latest user message.

    system_prompt = f"""
You are an advanced AI assistant specializing in iterative process refinement.
Your task is to:
1.  Analyze the provided 'Current JSON Process Description'.
2.  Consider the 'Conversation History', particularly the last AI question and the 'User's Latest Answer' to it.
3.  Based on the user's answer and the conversation, **update** the 'Current JSON Process Description' to be more accurate, complete, or clarified. The structure of the JSON should be preserved or logically extended.
4.  After updating the JSON, generate 2-3 new, specific, and actionable refinement questions about the *newly updated* JSON. These questions should guide the user to further improve the process.
5.  You MUST return your response as a single, valid JSON object containing two keys:
    -   `updated_json_process`: The modified JSON process description.
    -   `new_questions`: A JSON array of new question strings.

Example of your output format:
{{
  "updated_json_process": {{ ... the new JSON object ... }},
  "new_questions": ["New question 1 about updated JSON?", "New question 2 about updated JSON?"]
}}

Do not include any other text, explanations, or markdown formatting outside of this JSON object.
The user's latest answer is: "{user_answer}"
"""

    messages = [ChatMessage(role="system", content=system_prompt)]

    # Add existing conversation history
    # Ensure it's in ChatMessage format if not already
    for msg in conversation_history_list:
        if isinstance(msg, ChatMessage):
            messages.append(msg)
        elif isinstance(msg, dict) and "role" in msg and "content" in msg:
            messages.append(ChatMessage(role=msg["role"], content=msg["content"]))
        else:
            app.logger.warning(f"Skipping invalid message in conversation history: {msg}")


    # The user_content for this turn will primarily be the current JSON,
    # as the user's answer is already incorporated into the system prompt for emphasis
    # and the history provides the question context.
    user_prompt_content = f"Current JSON Process Description:\n```json\n{current_json_str}\n```\n\nPlease provide the updated JSON and new questions based on my latest answer (which you have in your system instructions) and the conversation history."

    messages.append(ChatMessage(role="user", content=user_prompt_content))

    app.logger.debug(f"Messages sent to Mistral for refinement: {messages}")

    try:
        chat_response = mistral_client.chat(
            model=MISTRAL_MODEL_FOR_REFINEMENT, # Using a potentially more capable model
            messages=messages,
            # response_format={"type": "json_object"} # Highly desirable here
        )

        raw_response_content = chat_response.choices[0].message.content
        app.logger.info(f"Raw Mistral response for refinement: {raw_response_content}")

        try:
            json_str = raw_response_content.strip()
            if json_str.startswith("```json"):
                json_str = json_str[7:-3].strip()
            elif json_str.startswith("```"):
                json_str = json_str[3:-3].strip()

            parsed_response = json.loads(json_str)

            updated_json = parsed_response.get("updated_json_process")
            new_questions = parsed_response.get("new_questions")

            if not isinstance(updated_json, dict):
                return None, None, "Mistral response did not contain a valid 'updated_json_process' object."
            if not isinstance(new_questions, list) or not all(isinstance(q, str) for q in new_questions):
                 # Allow empty list of new questions if process is considered complete by AI
                if new_questions is None or (isinstance(new_questions, list) and len(new_questions) == 0) :
                    app.logger.info("Mistral returned no new questions, assuming process is complete for now.")
                    new_questions = [] # Normalize to empty list
                else:
                    return updated_json, None, "Mistral response did not contain a valid 'new_questions' list of strings."

            return updated_json, new_questions, None

        except json.JSONDecodeError as e:
            app.logger.error(f"Failed to decode JSON refinement from Mistral: {e}. Raw: {raw_response_content}")
            return None, None, f"Mistral response for refinement was not valid JSON. Raw: {raw_response_content}"
        except Exception as e: # Catch other potential errors from parsing structure
            app.logger.error(f"Error parsing refined data structure: {e}. Raw: {raw_response_content}")
            return None, None, f"Mistral response structure for refinement was invalid. Raw: {raw_response_content}"


    except Exception as e:
        app.logger.error(f"Error calling Mistral API for refinement: {e}")
        return None, None, f"Error communicating with Mistral API for refinement: {str(e)}"


@app.route('/submit_answer', methods=['POST'])
def submit_answer_route():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON payload", "updated_json_process": None, "new_questions": None}), 400

    user_answer = data.get('answer')
    current_json = data.get('current_json') # This should be the actual JSON object
    conversation_history = data.get('conversation_history') # List of {role, content} dicts

    if not user_answer or not current_json or conversation_history is None: # Allow empty history
        return jsonify({"error": "Missing 'answer', 'current_json', or 'conversation_history' in request",
                        "updated_json_process": None, "new_questions": None}), 400

    updated_json, new_questions, error = get_refined_json_and_new_questions(
        current_json, user_answer, conversation_history
    )

    if error:
        return jsonify({"error": error, "updated_json_process": None, "new_questions": None}), 500

    return jsonify({
        "updated_json_process": updated_json,
        "new_questions": new_questions,
        "error": None
    })

@app.errorhandler(Exception)
def handle_general_exception(e):
    # Log the exception for server-side debugging
    app.logger.error(f"An unhandled exception occurred: {e}", exc_info=True)
    # Return a JSON response to the client
    # Be careful not to expose sensitive error details to the client in production
    response = {
        "error": "An unexpected server error occurred. Please try again later.",
        # "details": str(e) # Optionally include details in debug mode
    }
    if app.debug:
        response["details"] = str(e)

    return jsonify(response), 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
