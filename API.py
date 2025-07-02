import requests
import json
import os
from RealtimeSTT import AudioToTextRecorder


def query_mistral_api(prompt, api_key, model="mistral-tiny"):
    url = "https://api.mistral.ai/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    data = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7
    }

    try:
        response = requests.post(url, headers=headers, data=json.dumps(data))
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
        return response.json()['choices'][0]['message']['content']
    except requests.exceptions.RequestException as e:
        print(f"Error during API call: {e}")
        return None
    except KeyError as e:
        print(f"Error parsing JSON response: {e}")
        return None


def save_json_to_file(data, file_path):
    try:
        with open(file_path, 'w') as json_file:
            json.dump(data, json_file, indent=4)
        print(f"JSON saved to {file_path}")
    except IOError as e:
        print(f"Error saving JSON to file: {e}")


def load_json_from_file(file_path):
    try:
        with open(file_path, 'r') as json_file:
            return json.load(json_file)
    except FileNotFoundError:
        return None
    except IOError as e:
        print(f"Error loading JSON from file: {e}")
        return None


if __name__ == '__main__':
    # Replace with your actual API key
    api_key = "297hTst17WCMLU55pnxZlkKwz7AwKuLm"
    json_file_path = "bpmn_process.json"

    # Check if a JSON file already exists
    existing_json = load_json_from_file(json_file_path)

    if existing_json:
        print("Using existing JSON file:")
        print(json.dumps(existing_json, indent=4))
        # Start a new transcription process
        recorder = AudioToTextRecorder(input_device_index=0)
        recorder.start()
        input("Press Enter to stop recording...")
        recorder.stop()
        recording = recorder.text() + "\n" + existing_json.get("process_description", "")
        
    else:
        # Start a new transcription process
        recorder = AudioToTextRecorder(input_device_index=0)
        recorder.start()
        input("Press Enter to stop recording...")
        recorder.stop()
        recording = recorder.text()
        prompt = f"""
**Prompt für Fließtext-zu-BPMN-JSON-Konvertierung**

"Du bist ein Experte für BPMN (Business Process Model and Notation) und die Modellierung von Geschäftsprozessen. Deine Aufgabe ist es, einen gegebenen Fließtext, der einen Geschäftsprozess beschreibt, zu analysieren und daraus eine strukturierte JSON-Datei zu erstellen.

Die JSON-Datei soll die **logische Struktur** des Prozesses abbilden, ähnlich dem BPMN-Metamodell, das wir besprochen haben. Das bedeutet, du musst folgende Elemente und ihre Beziehungen identifizieren und in JSON darstellen:

* **Prozess-Informationen:** Ein allgemeiner Name und eine ID für den gesamten Prozess.
* **BPMN-Elemente (`elements` Array):**
    * **Start- und Endereignisse (`startEvent`, `endEvent`):** Markieren den Anfang und das Ende von Prozesspfaden.
    * **Aufgaben (`task`):** Einzelne Arbeitsschritte oder Aktivitäten.
    * **Gateways (`exclusiveGateway`, `parallelGateway`, `inclusiveGateway`):** Punkte im Prozess, an denen Entscheidungen getroffen, Pfade verzweigt oder zusammengeführt werden. Gib den Typ des Gateways korrekt an.
    * Jedes Element sollte eine eindeutige `id`, einen `type` (z.B. "task", "startEvent"), einen `name` und Listen für `incoming` und `outgoing` Sequence Flows (IDs der Flüsse) haben.
* **Sequenzflüsse (`sequenceFlows` Array):**
    * Jeder Flow sollte eine `id`, eine `sourceRef` (ID des Startelements) und eine `targetRef` (ID des Zielelements) haben.
    * Wenn es sich um einen Fluss handelt, der von einem exklusiven oder inklusiven Gateway ausgeht, füge ein Attribut `conditionExpression` hinzu, das die Bedingung beschreibt.
* **Pools und Lanes (optional, wenn im Text erkennbar):** Wenn der Text Verantwortlichkeiten oder Abteilungen erwähnt, die Teil des Prozesses sind, versuche, diese als `pools` und darin enthaltene `lanes` abzubilden. Gib die `elementsInLane` oder `elementsInPool` an, indem du die IDs der zugehörigen Elemente auflistest.

**Wichtige Hinweise für die Erstellung:**

1.  **Fokus auf Logik:** Konzentriere dich auf die **logische Abfolge und die Beziehungen** zwischen den Elementen. Die räumliche Anordnung (X/Y-Koordinaten) ist **nicht** relevant und soll **nicht** in der JSON-Datei enthalten sein.
2.  **Eindeutige IDs:** Generiere für jedes Element und jeden Sequenzfluss eindeutige, lesbare IDs (z.B. "Activity\_TaskA", "SequenceFlow\_1").
3.  **Bedingungen:** Achte genau auf Bedingungen bei Gateways. Formuliere die `conditionExpression` prägnant.
4.  **Klarheit vor Vollständigkeit:** Wenn ein Aspekt im Fließtext unklar ist oder nicht eindeutig einem BPMN-Konzept zugeordnet werden kann, triff eine sinnvolle Annahme oder lass das Detail weg, wenn es die Lesbarkeit der logischen Struktur beeinträchtigen würde.
5.  **Strenge JSON-Syntax:** Die Ausgabe muss valides JSON sein.

---

**Hier ist der Fließtext, den du analysieren sollst:**

{recording}
"""

        # Call the Mistral API with the provided prompt and API key
        response = query_mistral_api(prompt, api_key)

        if response:
            try:
                json_data = json.loads(response)  # Parse the response as JSON
                save_json_to_file(json_data, json_file_path)
            except json.JSONDecodeError as e:
                print(f"Error decoding API response as JSON: {e}")
        else:
            print("Failed to get a response from the API.")