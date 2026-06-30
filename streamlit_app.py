import streamlit as st
import os
import requests
import csv
import random
import io
import csv
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

API_KEY = os.environ.get("API_KEY")
import json

from google.oauth2 import service_account
from googleapiclient.discovery import build
import streamlit as st

def get_drive_service():
    """
    Authenticates with Google Cloud using Streamlit Secrets 
    and returns an authorized API client session.
    """
    # 1. Grab the raw credentials dictionary from your Streamlit App secrets
    credentials_info = st.secrets["gcp_service_account"]
    
    # 2. Convert that dictionary into an official Google OAuth2 Credentials object
    # The 'scope' tells Google exactly what permissions your app is asking for
    creds = service_account.Credentials.from_service_account_info(
        credentials_info, 
        scopes=["https://www.googleapis.com/auth/drive.file"]
    )
    
    # 3. Construct and return the 'service' client specifically for the Drive API (version 3)
    return build('drive', 'v3', credentials=creds)

st.set_page_config(layout="wide", page_title="Compare LLM Pipelines")

goals = {
    "Narrative":"""
        Write narratives to develop real or imagined experiences or events using effective technique, descriptive details, and clear event sequences.
            Orient the reader by establishing a situation and introducing a narrator and/or characters; organize an event sequence that unfolds naturally.
            Use dialogue and description to develop experiences and events or show the responses of characters to situations.
            Use a variety of transitional words and phrases to manage the sequence of events.
            Use concrete words and phrases and sensory details to convey experiences and events precisely.
            Provide a conclusion that follows from the narrated experiences or events.""",
    "Descriptive":"""
    Write informative/explanatory texts to examine a topic and convey ideas and information clearly.
        Introduce a topic clearly and group related information in paragraphs and sections; include formatting (e.g., headings).
        Develop the topic with facts, definitions, concrete details, quotations, or other information and examples related to the topic.
        Link ideas within categories of information using words and phrases (e.g., another, for example, also, because).
        Use precise language and domain-specific vocabulary to inform about or explain the topic.
        Provide a concluding statement or section related to the information or explanation presented.""",
    "Argumentative":"""
    Write opinion pieces on topics or texts, supporting a point of view with reasons and information.
        Introduce a topic or text clearly, state an opinion, and create an organizational structure in which related ideas are grouped to support the writer's purpose.
        Provide reasons that are supported by facts and details. For each reason, the student need to first introduce the argument; second develop and explain it; third prove it by providing examples, facts, and details; finally provide a conclusion for this reason.
        Link opinion and reasons using words and phrases (e.g., for instance, in order to, in addition). Focus on the use of words, conjunction, adverbials, logical phrases, and sentence structure to achieve coherence (logical arrangemnt and progression of ideas) and cohesion (linking sentences and paragraphs to connect ideas).
        Provide a concluding statement or section related to the opinion presented.
"""
}


with open("LEGACY_PROMPT.md", "r", encoding="utf-8") as file:
    LEGACY = file.read()

with open("NEW_PROMPT.md","r", encoding="utf-8") as file:
    NEW = file.read()


LOG_CSV = "logs.csv"

def response(system,history,formatted_input):
    
    url = 'https://hctlsrvb.edu.sot.tum.de/llm//v1/chat/completions'
    headers = {
    'Authorization': f'Bearer {API_KEY}',
    'Content-Type': 'application/json'
    }
    data = {
    "model": "gpt-oss-120b",
    "messages":[{"role": "system", "content": system}]+ history + [{"role":"user", "content":formatted_input}],
    "stream": False
    }
    response = requests.post(url, headers=headers, json=data)
    return response.json()["choices"][0]["message"]["content"]

def format_input(topic: str, essay: str, prompt: str) -> str:
    return f"<topic>{topic}</topic>\n<essay>{essay}</essay>\n<prompt>{prompt}</prompt>"

def format_system_prompt(legacy, new, language,writing_type):
    legacy = legacy.replace("{language}",language)
    new = new.replace("{language}",language).replace("{type}",writing_type).replace("{structure}",goals[writing_type])
    return legacy,new

def extract_output(response):
    if "<output>" in  response:
        output = response.rsplit("<output>",1)[1]
        pedagogy = response.rsplit("<output>",1)[0]
    else:
        output = response
        pedagogy = ""
    if "</output>" in response:
        output = output.replace("</output>","")
    return pedagogy, output


def get_model_history() -> list:
    """
    Keep only previous chosen tutor turns in model history.
    Convert older string-only history safely if a user already has session data.
    """
    if "model_history" not in st.session_state:
        st.session_state["model_history"] = []

    converted = []
    for item in st.session_state.get("model_history", []):
        if isinstance(item, dict) and "role" in item and "content" in item:
            converted.append(item)

    # Backward compatibility with the old app, which stored chosen outputs only.
    if not converted and st.session_state.get("history"):
        for item in st.session_state.get("history", []):
            if isinstance(item, dict) and "content" in item:
                converted.append({"role": "assistant", "content": item["content"]})
            else:
                converted.append({"role": "assistant", "content": str(item)})

    st.session_state["model_history"] = converted
    return converted[:]


def safe_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()

import csv
import io
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from googleapiclient.errors import HttpError

def append_log_row(row: dict):
    """
    Appends a row to a CSV file hosted on Google Drive with explicit 
    connection, existence, and permission validations.
    """
    fieldnames = [
        "topic", "essay", "history", "prompt", 
        "thinking1", "thinking2", "output1", "output2", "choice"
    ]
    LOG_FILE_ID = "1n7Mwe2_qghkPvZ2ElQ6J2p0_dxzf92IE"
    
    # --- STEP 1: Connect to Google Drive ---
    try:
        service = get_drive_service()
        if not service:
            raise ValueError("The 'get_drive_service()' function returned None. Check authentication setup.")
    except Exception as e:
        st.info(f"❌ CONNECTION ERROR: Failed to authenticate or connect to Google Drive API.\nDetails: {e}")
        return

    # --- STEP 2: Verify File Existence and Permissions ---
    try:
        # Fetch file metadata to check capabilities (permissions)
        metadata = service.files().get(fileId=LOG_FILE_ID, fields="capabilities").execute()
        
        # Verify if the authenticated account can actually edit this file
        can_edit = metadata.get("capabilities", {}).get("canEdit", False)
        if not can_edit:
            st.info(f"⚠️ PERMISSION WARNING: File found, but your account does not have permission to modify it.")
            st.info("Please check that the file is shared with write/editor access to your service account/email.")
            return
            
    except HttpError as e:
        if e.resp.status == 404:
            st.info(f"❌ FILE NOT FOUND: Could not find file ID '{LOG_FILE_ID}'.")
            st.info("Double-check the ID, ensure it isn't deleted, and verify it is shared with your API credentials.")
        else:
            st.info(f"❌ API ERROR while verifying file: Status {e.resp.status} - {e.reason}")
        return
    except Exception as e:
        st.info(f"❌ UNEXPECTED ERROR during file verification: {e}")
        return

    # --- STEP 3: Download Existing Content ---
    existing_text = ""
    try:
        request = service.files().get_media(fileId=LOG_FILE_ID)
        downloaded_bytes = io.BytesIO()
        downloader = MediaIoBaseDownload(downloaded_bytes, request)
        
        done = False
        while not done:
            status, done = downloader.next_chunk()
            
        downloaded_bytes.seek(0)
        existing_text = downloaded_bytes.read().decode('utf-8')
        st.info("📥 Successfully downloaded existing log data.")
    
    except Exception as e:
        # Since we verified the file exists above, a failure here points to a network glitch
        st.info(f"⚠️ DOWNLOAD WARNING: File exists but failed to read its contents. Starting with an empty file. Details: {e}")

    # --- STEP 4: Append the New Row in Memory ---
    output_buffer = io.StringIO()
    writer = csv.DictWriter(output_buffer, fieldnames=fieldnames, extrasaction="ignore")
    
    if not existing_text.strip():
        st.info("📝 CSV appears to be empty or new. Writing headers and first row...")
        writer.writeheader()
        writer.writerow(row)
        final_csv_text = output_buffer.getvalue()
    else:
        writer.writerow(row)
        new_row_text = output_buffer.getvalue()
        if not existing_text.endswith('\n'):
            existing_text += '\n'
        final_csv_text = existing_text + new_row_text

    # --- STEP 5: Upload Updated Content ---
    final_bytes = io.BytesIO(final_csv_text.encode('utf-8'))
    media = MediaIoBaseUpload(final_bytes, mimetype='text/csv', resumable=False)
    
    try:
        service.files().update(
            fileId=LOG_FILE_ID,
            media_body=media
        ).execute()
        st.info("✅ SUCCESS: Row successfully appended and synced to Google Drive.")
    except HttpError as e:
        st.info(f"❌ UPLOAD FAILED (API Error): Status {e.resp.status} - {e.reason}")
    except Exception as e:
        st.info(f"❌ UPLOAD FAILED (Network/System Error): {e}")


def run_pipelines(legacy,new, language: str, writing_type: str, topic: str, essay: str, prompt: str) -> dict:
    formatted_input = format_input(topic, essay, prompt)
    history_for_model = get_model_history()

    legacy,new = format_system_prompt(legacy,new,language,writing_type)
    # Pipeline 1: direct answer with hidden thinking/output tags.
    resp1 = response(legacy, history_for_model, formatted_input)
    think1, output1 = extract_output(resp1)

    # Pipeline 2: pedagogy plan first, then student-facing answer.
    resp_b1 = response(new, history_for_model, formatted_input)
    think2, output2 = extract_output(resp_b1)


    choices = [
        {
            "id": "pipeline_1",
            "choice": "Pipeline 1",
            "output": output1,
            "thinking": think1,
        },
        {
            "id": "pipeline_2",
            "choice": "Pipeline 2",
            "output": output2,
            "thinking": think2,
        },
    ]
    random.shuffle(choices)

    return {
        "topic": topic,
        "essay": essay,
        "prompt": prompt,
        "formatted_input": formatted_input,
        "choices": choices,
        "output1": output1,
        "output2": output2,
        "thinking1": think1,
        "thinking2": think2,
    }


if "history" not in st.session_state:
    st.session_state["history"] = []  # previous chosen tutor outputs, kept for compatibility

if "chat_log" not in st.session_state:
    st.session_state["chat_log"] = []  # visible chat turns: {"role": "user"|"assistant", "content": str}

if "model_history" not in st.session_state:
    st.session_state["model_history"] = []  # messages passed back into the LLM calls

if "interaction_count" not in st.session_state:
    st.session_state["interaction_count"] = 0

if "pending_result" not in st.session_state:
    st.session_state["pending_result"] = None


# --- Styling ---
st.markdown(
    """
    <style>
        .block-container {
            padding-top: 1.6rem;
            padding-bottom: 1rem;
            max-width: 1500px;
        }

        .app-title {
            font-size: 2.1rem;
            font-weight: 800;
            letter-spacing: -0.03em;
            margin-bottom: 0.2rem;
        }

        .app-subtitle {
            color: #667085;
            font-size: 1rem;
            margin-bottom: 1.25rem;
        }

        .panel {
            border: 1px solid #EAECF0;
            border-radius: 22px;
            padding: 1.2rem 1.2rem 1.4rem 1.2rem;
            background: linear-gradient(180deg, #FFFFFF 0%, #FCFCFD 100%);
            box-shadow: 0 10px 30px rgba(16, 24, 40, 0.06);
        }

        .panel-title {
            font-size: 1.15rem;
            font-weight: 750;
            margin-bottom: 0.15rem;
        }

        .panel-caption {
            color: #667085;
            font-size: 0.9rem;
            margin-bottom: 1rem;
        }

        .chat-frame {
            min-height: 560px;
            max-height: 640px;
            overflow-y: auto;
            padding: 0.75rem;
            border: 1px solid #EAECF0;
            border-radius: 18px;
            background: #F9FAFB;
            margin-bottom: 1rem;
        }

        .empty-chat {
            text-align: center;
            color: #98A2B3;
            border: 1px dashed #D0D5DD;
            border-radius: 16px;
            padding: 2rem 1rem;
            margin: 1rem 0;
            background: white;
        }

        .user-bubble, .assistant-bubble {
            padding: 0.7rem 0.9rem;
            border-radius: 16px;
            margin: 0.45rem 0;
            line-height: 1.45;
            font-size: 0.96rem;
        }

        .user-bubble {
            margin-left: 18%;
            background: #EEF4FF;
            border: 1px solid #D1E0FF;
        }

        .assistant-bubble {
            margin-right: 18%;
            background: #FFFFFF;
            border: 1px solid #EAECF0;
        }

        .pending-note {
            color: #667085;
            font-size: 0.9rem;
            margin: 0.25rem 0 0.6rem 0;
        }

        div[data-testid="stButton"] > button {
            white-space: normal;
            height: auto;
            min-height: 88px;
            padding: 1rem 1.05rem;
            border-radius: 18px;
            border: 1px solid #D0D5DD;
            background: #FFFFFF;
            box-shadow: 0 6px 18px rgba(16, 24, 40, 0.06);
            text-align: left;
            justify-content: flex-start;
            align-items: flex-start;
            line-height: 1.45;
            font-weight: 520;
        }

        div[data-testid="stButton"] > button:hover {
            border-color: #84ADFF;
            box-shadow: 0 10px 28px rgba(16, 24, 40, 0.10);
            transform: translateY(-1px);
        }

        textarea {
            border-radius: 14px !important;
        }

        .small-muted {
            color: #667085;
            font-size: 0.86rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


st.markdown('<div class="app-title">Writing Tutor Workspace</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="app-subtitle">Write on the left. Chat with the tutor on the right. Choose the reply you prefer by clicking it.</div>',
    unsafe_allow_html=True,
)

left_col, right_col = st.columns([1.18, 0.82], gap="large")


# --- Left column: essay workspace ---
with left_col:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">Essay workspace</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="panel-caption">Set the task, then draft and revise your essay here.</div>',
        unsafe_allow_html=True,
    )
    language = st.text_input("Language", value="", placeholder="In what Language are you writing?")
    writing_type = st.selectbox("Type of writing", list(goals.keys()))

    topic = st.text_input("Topic", value="", placeholder="What are you writing about?")
    essay = st.text_area(
        "Your essay",
        value="",
        height=560,
        placeholder="Write your essay here. Keep your tutor question in the chat box on the right.",
    )

    st.markdown(
        '<div class="small-muted">Tip: keep your essay draft here, not inside the chat prompt.</div>',
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)


# --- Right column: chatbot + response preference cards ---
with right_col:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">Tutor chat</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="panel-caption">Ask for feedback, then click the tutor reply you prefer.</div>',
        unsafe_allow_html=True,
    )


    if not st.session_state["chat_log"] and not st.session_state["pending_result"]:
        st.markdown(
            '<div class="empty-chat">No messages yet.<br>Ask the tutor for one small piece of help.</div>',
            unsafe_allow_html=True,
        )

    for turn in st.session_state["chat_log"]:
        role_class = "user-bubble" if turn["role"] == "user" else "assistant-bubble"
        speaker = "You" if turn["role"] == "user" else "Tutor"
        st.markdown(
            f'<div class="{role_class}"><strong>{speaker}</strong><br>{turn["content"]}</div>',
            unsafe_allow_html=True,
        )

    pending = st.session_state["pending_result"]
    if pending:
        st.markdown(
            f'<div class="user-bubble"><strong>You</strong><br>{pending["prompt"]}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="pending-note">Choose the tutor reply you prefer:</div>',
            unsafe_allow_html=True,
        )

    st.markdown("</div>", unsafe_allow_html=True)

    if pending:
        for idx, choice in enumerate(pending["choices"]):
            button_label = choice["output"]
            if st.button(button_label, key=f"choose_{idx}_{choice['id']}", use_container_width=True):
                row = {
                    "topic": pending["topic"],
                    "essay": pending["essay"],
                    "history": json.dumps(st.session_state["model_history"], ensure_ascii=False),
                    "prompt": pending["prompt"],
                    "thinking1": pending["thinking1"],
                    "thinking2": pending["thinking2"],
                    "output1": pending["output1"],
                    "output2": pending["output2"],
                    "choice": choice["choice"],
                }
                append_log_row(row)

                st.session_state["chat_log"].append({"role": "user", "content": pending["prompt"]})
                st.session_state["chat_log"].append({"role": "assistant", "content": choice["output"]})

                st.session_state["history"].append(choice["output"])
                st.session_state["model_history"].append(
                    {"role": "user", "content": pending["formatted_input"]}
                )
                st.session_state["model_history"].append(
                    {"role": "assistant", "content": choice["output"]}
                )

                st.session_state["interaction_count"] += 1
                st.session_state["pending_result"] = None
                safe_rerun()

        st.markdown(
            '<div class="small-muted">The selected reply will be saved in the conversation history.</div>',
            unsafe_allow_html=True,
        )

    with st.form("chat_form", clear_on_submit=True):
        prompt = st.text_area(
            "Message to tutor",
            value="",
            height=110,
            placeholder="Ask for feedback or tell the tutor what you are stuck on.",
        )
        submit = st.form_submit_button("Send", use_container_width=True)

    if submit:
        if not prompt.strip():
            st.warning("Write a short message to the tutor first.")
        else:
            try:
                with st.spinner("Preparing tutor replies..."):
                    st.session_state["pending_result"] = run_pipelines(
                        legacy=LEGACY,
                        new = NEW,
                        language=language,
                        writing_type=writing_type,
                        topic=topic,
                        essay=essay,
                        prompt=prompt.strip(),
                    )
                safe_rerun()
            except Exception as exc:
                st.error(
                    "The tutor replies could not be generated. Check that your response(...) function is available and working."
                )
                with st.expander("Developer error details"):
                    st.exception(exc)

    col_restart, col_clear_pending = st.columns(2)
    with col_restart:
        if st.button("Restart", use_container_width=True):
            st.session_state["history"] = []
            st.session_state["chat_log"] = []
            st.session_state["model_history"] = []
            st.session_state["interaction_count"] = 0
            st.session_state["pending_result"] = None
            safe_rerun()

    with col_clear_pending:
        if st.button("Skip choices", use_container_width=True):
            st.session_state["pending_result"] = None
            safe_rerun()

    st.markdown("</div>", unsafe_allow_html=True)


st.caption(f"Interactions saved to `{LOG_CSV}` after a tutor reply is selected.")