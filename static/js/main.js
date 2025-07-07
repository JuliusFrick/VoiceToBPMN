document.addEventListener('DOMContentLoaded', () => {
    const startRecordBtn = document.getElementById('startRecordBtn');
    const stopRecordBtn = document.getElementById('stopRecordBtn');
    const jsonOutput = document.getElementById('jsonOutput');
    const chatMessages = document.getElementById('chatMessages');
    const userInput = document.getElementById('userInput');
    const sendAnswerBtn = document.getElementById('sendAnswerBtn');
    const statusMessage = document.getElementById('statusMessage');

    let mediaRecorder;
    let audioChunks = [];
    let currentProcessJSON = null; // To store the latest JSON state
    let conversationHistory = []; // To store the chat for context

    console.log("JavaScript loaded. Elements selected.");

    if (startRecordBtn) {
        startRecordBtn.addEventListener('click', async () => {
            console.log("Start Recording button clicked");
            if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
                try {
                    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                    mediaRecorder = new MediaRecorder(stream);

                    mediaRecorder.ondataavailable = (event) => {
                        audioChunks.push(event.data);
                    };

                    mediaRecorder.onstart = () => {
                        console.log("Recording started");
                        statusMessage.textContent = "Status: Recording...";
                        startRecordBtn.disabled = true;
                        stopRecordBtn.disabled = false;
                        audioChunks = [];
                    };

                    mediaRecorder.onstop = async () => {
                        console.log("Recording stopped");
                        statusMessage.textContent = "Status: Processing audio...";
                        const audioBlob = new Blob(audioChunks, { type: 'audio/webm' }); // Or appropriate type
                        audioChunks = []; // Reset for next recording

                        // TODO: Send audioBlob to backend
                        console.log("Audio Blob created, size:", audioBlob.size);
                        statusMessage.textContent = "Status: Audio recorded. Ready to send (not implemented).";
                        startRecordBtn.disabled = false;
                        stopRecordBtn.disabled = true;

                        // Send audioBlob to backend
                        console.log("Audio Blob created, type:", audioBlob.type, "size:", audioBlob.size);
                        await processAudio(audioBlob);
                    };

                    mediaRecorder.start();
                } catch (err) {
                    console.error("Error accessing microphone:", err);
                    statusMessage.textContent = "Error: Could not access microphone. " + err.message;
                    alert("Error accessing microphone: " + err.message);
                    startRecordBtn.disabled = false;
                    stopRecordBtn.disabled = true;
                }
            } else {
                console.error("getUserMedia not supported on your browser!");
                statusMessage.textContent = "Error: Audio recording not supported on this browser.";
                alert("Audio recording is not supported on your browser.");
            }
        });
    } else {
        console.error("Start Record Button not found");
    }

    if (stopRecordBtn) {
        stopRecordBtn.addEventListener('click', () => {
            console.log("Stop Recording button clicked");
            if (mediaRecorder && mediaRecorder.state === "recording") {
                mediaRecorder.stop();
                statusMessage.textContent = "Status: Stopping recording...";
                stopRecordBtn.disabled = true; // Disable stop until processing is done or fails
                // startRecordBtn will be re-enabled in processAudio or its error handling
            }
        });
    } else {
        console.error("Stop Record Button not found");
    }

    if (sendAnswerBtn) {
        sendAnswerBtn.addEventListener('click', () => {
            const answer = userInput.value.trim();
            if (answer) {
                console.log("User answer:", answer);
                addMessageToChat(answer, 'user');
                userInput.value = ''; // Clear input

                if (!currentProcessJSON) {
                    addMessageToChat("There is no current process JSON to refine. Please start by recording a process.", 'ai');
                    statusMessage.textContent = "Status: Waiting for initial process.";
                    return;
                }

                // Disable input while processing
                userInput.disabled = true;
                sendAnswerBtn.disabled = true;
                statusMessage.textContent = "Status: Submitting answer and refining process...";

                submitAnswerAndRefine(answer, currentProcessJSON, conversationHistory);
            }
        });
    } else {
        console.error("Send Answer Button not found");
    }

    async function processAudio(audioBlob) {
        const formData = new FormData();
        // The third argument to append is the filename. Ensure it has a reasonable extension.
        // Common types from MediaRecorder are 'audio/webm;codecs=opus' or 'audio/ogg;codecs=opus'.
        // Sending as .webm should be fine for pydub to auto-detect.
        formData.append('audio_data', audioBlob, 'recording.webm');

        try {
            statusMessage.textContent = "Status: Uploading and transcribing audio...";
            jsonOutput.textContent = "Processing..."; // Placeholder while waiting

            const response = await fetch('/process_audio', {
                method: 'POST',
                body: formData,
            });

            if (!response.ok) {
                // Try to parse error message from server if JSON, otherwise use status text
                let errorMsg = `HTTP error! status: ${response.status} ${response.statusText}`;
                try {
                    const errorData = await response.json();
                    errorMsg = errorData.error || errorMsg;
                } catch (e) {
                    // Not a JSON error response, stick with HTTP status
                }
                throw new Error(errorMsg);
            }

            const result = await response.json();

            if (result.error) {
                throw new Error(result.error);
            }

            if (result.error) { // This should catch errors from the backend processing (transcription, Mistral)
                throw new Error(result.error);
            }

            if (result.json_process) {
                jsonOutput.textContent = JSON.stringify(result.json_process, null, 2); // Pretty print JSON
                currentProcessJSON = result.json_process; // Store for later use
                statusMessage.textContent = "Status: JSON Process generated successfully. Fetching questions...";
                await fetchAndDisplayRefinementQuestions(currentProcessJSON);
            } else if (result.transcribed_text) {
                // Fallback if JSON is missing but transcription exists
                currentProcessJSON = null; // Clear any previous JSON
                jsonOutput.textContent = `Transcription received, but no JSON process generated.\nTranscribed Text: ${result.transcribed_text}`;
                statusMessage.textContent = "Status: Transcription successful, but JSON generation failed or was empty.";
            } else {
                // This case should ideally be covered by result.error, but as a fallback
                jsonOutput.textContent = "Failed to get a process or transcription from the server.";
                statusMessage.textContent = "Status: Failed to retrieve data.";
            }

        } catch (error) { // This catches fetch errors or errors thrown from response handling
            console.error('Error in processAudio function:', error);
            statusMessage.textContent = `Error: ${error.message}`;
            jsonOutput.textContent = "Failed to process audio.";
        } finally {
            // Re-enable buttons appropriately after processing
            startRecordBtn.disabled = false;
            stopRecordBtn.disabled = true; // Stop should remain disabled until next recording starts
        }
    }

    function addMessageToChat(message, sender) {
        const messageDiv = document.createElement('div');
        messageDiv.classList.add('message', sender === 'user' ? 'user-message' : 'ai-message');
        messageDiv.textContent = message;
        chatMessages.appendChild(messageDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight; // Scroll to bottom

        // Add to conversation history (simple version)
        conversationHistory.push({role: sender === 'user' ? 'user' : 'assistant', content: message});
    }

    async function fetchAndDisplayRefinementQuestions(jsonProcess) {
        if (!jsonProcess) {
            statusMessage.textContent = "Status: Cannot fetch questions without a JSON process.";
            return;
        }

        statusMessage.textContent = "Status: Fetching refinement questions...";
        try {
            const response = await fetch('/get_refinement_questions', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ current_json: jsonProcess }), // Send the actual JSON object
            });

            if (!response.ok) {
                let errorMsg = `Error fetching questions: ${response.status} ${response.statusText}`;
                try {
                    const errorData = await response.json();
                    errorMsg = errorData.error || errorMsg;
                } catch (e) { /* Ignore if error response isn't JSON */ }
                throw new Error(errorMsg);
            }

            const data = await response.json();

            if (data.error) {
                throw new Error(data.error);
            }

            if (data.questions && data.questions.length > 0) {
                data.questions.forEach(question => {
                    addMessageToChat(question, 'ai');
                });
                statusMessage.textContent = "Status: Questions received. Please answer in the chat.";
            } else {
                addMessageToChat("No further refinement questions at this time. You can try rephrasing your process or starting over if needed.", 'ai');
                statusMessage.textContent = "Status: No specific questions, process might be clear or need broader input.";
            }

        } catch (error) {
            console.error("Error fetching refinement questions:", error);
            statusMessage.textContent = `Error: ${error.message}`;
            addMessageToChat(`Sorry, I couldn't fetch refinement questions: ${error.message}`, 'ai');
        }
    }

    // Event listener for Enter key in the input field
    userInput.addEventListener('keypress', function(event) {
        if (event.key === 'Enter' && !sendAnswerBtn.disabled) { // Also check if button is enabled
            event.preventDefault(); // Prevent default form submission if it were in a form
            sendAnswerBtn.click(); // Trigger send button click
        }
    });

    async function submitAnswerAndRefine(answer, currentJson, convHistory) {
        try {
            const response = await fetch('/submit_answer', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                // Send the whole conversation history, the backend will use the last parts.
                // currentJson should be an object, not a string here.
                body: JSON.stringify({
                    answer: answer,
                    current_json: currentJson,
                    conversation_history: convHistory
                }),
            });

            if (!response.ok) {
                let errorMsg = `Error submitting answer: ${response.status} ${response.statusText}`;
                try {
                    const errorData = await response.json();
                    errorMsg = errorData.error || errorMsg;
                } catch (e) { /* Ignore if error response isn't JSON */ }
                throw new Error(errorMsg);
            }

            const data = await response.json();

            if (data.error) {
                throw new Error(data.error);
            }

            // Update JSON display
            if (data.updated_json_process) {
                jsonOutput.textContent = JSON.stringify(data.updated_json_process, null, 2);
                currentProcessJSON = data.updated_json_process; // Update state
                statusMessage.textContent = "Status: Process updated. See new questions or message below.";
            } else {
                // This shouldn't happen if there's no error, but good to handle.
                statusMessage.textContent = "Status: Answer submitted, but no updated JSON received.";
            }

            // Display new questions or completion message
            if (data.new_questions && data.new_questions.length > 0) {
                data.new_questions.forEach(question => {
                    addMessageToChat(question, 'ai');
                });
            } else {
                addMessageToChat("Process refined. No further questions at this moment.", 'ai');
                statusMessage.textContent = "Status: Process refined. It seems complete for now!";
            }

        } catch (error) {
            console.error("Error submitting answer:", error);
            statusMessage.textContent = `Error: ${error.message}`;
            addMessageToChat(`Sorry, I couldn't process your answer: ${error.message}`, 'ai');
        } finally {
            // Re-enable input
            userInput.disabled = false;
            sendAnswerBtn.disabled = false;
            userInput.focus(); // Focus back on input for next answer
        }
    }
});
