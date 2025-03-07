
import os
import time
import csv
import re
import requests
import tempfile
import pandas as pd
import streamlit as st
import firebase_admin
from firebase_admin import credentials, auth
from bs4 import BeautifulSoup
from st_aggrid import AgGrid, GridOptionsBuilder

# Initialize Firebase only once
if not firebase_admin._apps:
    cred = credentials.Certificate('login-page-e886b-0aac38c36d9f.json')
    firebase_admin.initialize_app(cred)


FASTAPI_URL = "http://127.0.0.1:8000"

FIREBASE_WEB_API_KEY = "AIzaSyCct_-zXK4ZSknaGENqGbDfrC1RpFuXkvM"

# Session state for user authentication
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

video_placeholder = st.empty()
if "uploaded_video_path" in st.session_state:
    video_placeholder.video(st.session_state["uploaded_video_path"])

ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}

# Firebase Authentication Functions
def firebase_login(email, password):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_WEB_API_KEY}"
    payload = {"email": email, "password": password, "returnSecureToken": True}
    response = requests.post(url, json=payload)
    return response.json() if response.status_code == 200 else None

def firebase_signup(email, password):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={FIREBASE_WEB_API_KEY}"
    payload = {"email": email, "password": password, "returnSecureToken": True}
    response = requests.post(url, json=payload)
    return response.json() if response.status_code == 200 else None

def login_page():
    """Login and Signup Page"""
    st.title("🔐 Welcome!")

    # Buttons to toggle between login and signup
    col1, col2 = st.columns(2)
    login_clicked = col1.button("Login")
    signup_clicked = col2.button("Sign Up")

    if "show_login" not in st.session_state:
        st.session_state["show_login"] = True  # Default to login form

    if login_clicked:
        st.session_state["show_login"] = True

    if signup_clicked:
        st.session_state["show_login"] = False

    # Display the corresponding form
    if st.session_state["show_login"]:
        st.subheader("🔑 Login")
        email = st.text_input("📧 Email Address")
        password = st.text_input("🔒 Password", type="password")

        if st.button("Login Now"):
            user_data = firebase_login(email, password)
            if user_data and "idToken" in user_data:
                st.session_state["authenticated"] = True
                st.session_state["user_email"] = email
                st.toast("✅ Login Successful! Redirecting...")
                st.rerun()
            else:
                st.error("❌ Invalid Email or Password!")

    else:
        st.subheader("🆕 Sign Up")
        email = st.text_input("📧 Email Address")
        password = st.text_input("🔒 Password", type="password")

        if st.button("Create Account"):
            user_data = firebase_signup(email, password)
            if user_data and "idToken" in user_data:
                st.success("🎉 Account Created Successfully! Please login now.")
                st.balloons()
            else:
                st.error("❌ Error creating account. Try a different email.")


def video_upload_page():
    """Video Upload and Playback Page"""
    # st.title("🎥 VIDEO PLAYER")
    st.sidebar.button("🚪Logout", on_click=lambda: st.session_state.update({"authenticated": False}))



    def is_valid_video_file(filename: str) -> bool:
        return any(filename.lower().endswith(ext) for ext in ALLOWED_EXTENSIONS)

    st.sidebar.header("📂 Upload Video File")
    uploaded_file = st.sidebar.file_uploader("Upload a video", type=["mp4", "avi", "mov"], label_visibility="collapsed")
    if uploaded_file is not None:
        if not is_valid_video_file(uploaded_file.name):
            st.error("🚨 Please upload a valid video file!")
        else:
            temp_file_path = os.path.join(tempfile.gettempdir(), uploaded_file.name)
            with open(temp_file_path, "wb") as temp_file:
                temp_file.write(uploaded_file.read())

            try:
                with open(temp_file_path, "rb") as f:
                    response = requests.post(f"{FASTAPI_URL}/upload_video/", files={"file": f}, timeout=30)
                
                if response.status_code == 200:
                    data = response.json()

                    if "initial_time" not in data or "end_time" not in data:
                        st.error("🚨 Initial and end time not extracted!")
                    elif data["initial_time"] >= data["end_time"]:
                        st.error("🚨 Invalid timestamps: Initial time cannot be greater than or equal to end time!")
                    else:
                        st.session_state["uploaded_video_path"] = data["file_path"]
                        st.session_state["initial_time"] = data["initial_time"]
                        st.session_state["end_time"] = data["end_time"]
                        st.session_state["video_uploaded"] = True

                        # Display video
                        video_placeholder.video(st.session_state["uploaded_video_path"])

                        col1, col2 = st.columns([1, 1])
                        with col1:
                            st.markdown(f"**Initial Time:** {data['initial_time']}")
                        with col2:
                            st.markdown(f"<p style='text-align: right;'><b>End Time:</b> {data['end_time']}</p>", unsafe_allow_html=True)
                else:
                    st.error("🚨 Error uploading video!")
            except requests.exceptions.Timeout:
                st.error("🚨 Server is not responding. Please try again later.")
            except Exception as e:
                st.error(f"🚨 An unexpected error occurred: {str(e)}")


    st.sidebar.header("📄 Upload CSV / Data Crawling File")
    uploaded_file = st.sidebar.file_uploader("Upload your file", type=["csv", "xls", "xlsx"], label_visibility="collapsed")
    def parse_data(raw_text):
        field_patterns = {
            "Registration Number": r"REGISTRATION NUMBER\s*:\s*(\d+)",
            "Full Name": r"FULL NAME\s*:\s*([A-Za-z\s]+)",
            "Mobile": r"MOBILE\s*:\s*(\d{10})",
            "Company": r"COMPANY\s*:\s*([\w\s&.,-]+)",
            "Designation": r"DESIGNATION\s*:\s*([\w\s&.,-]+)",
            "Address": r"ADDRESS\s*:\s*([\w\s&.,-]+)",
            "City": r"CITY\s*:\s*([\w\s]+)",
            "State": r"STATE\s*:\s*([\w\s]+)",
            "Pincode": r"PINCODE\s*:\s*(\d{6})",
            "Email": r"EMAIL\s*:\s*([\w.\-]+@[\w.\-]+\.\w+)",
        }
        parsed_data = {}
        for field, pattern in field_patterns.items():
            match = re.search(pattern, raw_text, re.IGNORECASE)
            value = match.group(1).strip() if match else ""
            value = re.sub(r'\b(MOBILE|DESIGNATION|ADDRESS|CITY|STATE|PINCODE)\b', '', value, flags=re.IGNORECASE).strip()
            parsed_data[field] = value
        return parsed_data if parsed_data.get("Registration Number") else None

    def process_urls(excel_data, output_file_path):
        fieldnames = ["Registration Number", "Full Name", "Mobile", "Company", "Designation",
                    "Address", "City", "State", "Pincode", "Email", "Date", "Time"]
        seen_entries = set()
        with open(output_file_path, mode="w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            for _, row in excel_data.iterrows():
                url, date, time = row["Data"], row.get("Date", ""), row.get("Time", "")
                if not url.startswith("https://www.smartexpos.in/vr/pass/"):
                    st.warning(f"Skipping invalid URL: {url}")
                    continue
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5",
                    "Referer": "https://www.smartexpos.in/",
                    "Connection": "keep-alive"
                }

                try:
                    response = requests.get(url, headers=headers, timeout=15)
                    response.raise_for_status()
                except requests.RequestException as e:
                    st.error(f"Network error: {e}")
                    continue
                soup = BeautifulSoup(response.content, "html.parser")
                table = soup.find('table')
                if not table:
                    st.error("Error: No table found.")
                    continue
                raw_text = table.get_text(" ", strip=True)
                parsed_data = parse_data(raw_text)
                if not parsed_data:
                    st.error("Error: Data parsing failed.")
                    continue
                entry_id = f"{parsed_data['Registration Number']}|{parsed_data['Full Name']}"
                if entry_id not in seen_entries:
                    seen_entries.add(entry_id)
                    parsed_data.update({"Date": date, "Time": time})
                    writer.writerow(parsed_data)
        st.success(f"Data saved to {output_file_path}")
        return pd.read_csv(output_file_path)
    if uploaded_file:
        file_extension = uploaded_file.name.split('.')[-1].lower()

        # Show spinner based on file type
        with st.spinner("🌐 Crawling data from file... Please wait!" if file_extension == "csv" else "📂 Processing CSV file..."):
            # Read CSV or Excel
            df = pd.read_csv(uploaded_file) if file_extension == "csv" else pd.read_excel(uploaded_file, engine='openpyxl')

            output_path = os.path.join(os.getcwd(), "processed_data.csv")

            # Process only if "Data" column exists
            if "Data" in df.columns:
                df = process_urls(df, output_path)

            # Store in session state
            st.session_state["csv_data"] = df
    else:
        # Clear session state when file is removed
        st.session_state.pop("csv_data", None)
        st.session_state.pop("filtered_data", None)

    if "csv_data" in st.session_state:
        column_name = st.sidebar.selectbox("🔽 Select Column", st.session_state["csv_data"].columns)
        if column_name:
            unique_values = st.session_state["csv_data"][column_name].dropna().unique()
            selected_value = st.sidebar.selectbox("🎯 Select Value", unique_values)
            if selected_value and st.sidebar.button("🔍 Filter Data"):
                st.session_state["filtered_data"] = st.session_state["csv_data"][st.session_state["csv_data"][column_name] == selected_value]
                try:
                    response = requests.post(
                        f"{FASTAPI_URL}/filter_csv/",
                        data={"file_path": st.session_state["csv_data"], "column": column_name, "value": selected_value}
                    )
                    if response.status_code == 200:
                        st.session_state["filtered_data"] = response.json()["filtered_data"]
                        st.session_state["selected_column"] = column_name
                except Exception as e:
                    st.sidebar.error(f"⚠️ Error during filtering: {e}")



    if "filtered_data" in st.session_state:
        df_filtered = pd.DataFrame(st.session_state["filtered_data"])

        # Convert all column names to lowercase for consistency
        df_filtered.columns = df_filtered.columns.str.lower()

        st.write("### 📊 Filtered Data")

        # Set up Ag-Grid Table
        gb = GridOptionsBuilder.from_dataframe(df_filtered)
        gb.configure_selection("single", use_checkbox=True)
        grid_options = gb.build()

        selected_rows = AgGrid(df_filtered, gridOptions=grid_options, height=300)["selected_rows"]
        
        if selected_rows is not None and len(selected_rows) > 0:  # ✅ Fix NoneType issue
            selected_df = pd.DataFrame(selected_rows)  # Convert selected rows to DataFrame
            
            if "time" in selected_df.columns:  # ✅ Ensure "time" column exists
                selected_time = selected_df.iloc[0]["time"]  # ✅ Access first row's "time" value

                if selected_time:  # ✅ Ensure "time" is not None or empty
                    try:
                        response = requests.post(
                            f"{FASTAPI_URL}/jump_to_time/",
                            data={"initial_time": st.session_state["initial_time"], "jump_time": selected_time}
                        )
                        if response.status_code == 200:
                            jump_seconds = response.json().get("jump_seconds")

                            if jump_seconds is not None and isinstance(jump_seconds, (int, float)) and jump_seconds >= 0:
                                # ✅ Ensure the selected time matches video timestamps
                                if abs(jump_seconds - selected_time) > 1:  # Adjust threshold if needed
                                    st.error("🚨 Selected row time and video time do not match! Please check your data.")
                                else:
                                    st.success(f"⏩ Jumping to Selected Row Value")
                                    video_placeholder.video(st.session_state["uploaded_video_path"], start_time=int(jump_seconds))
                            else:
                                st.error("🚨 Invalid jump time received from API.")  # ✅ Edge case for missing response
                        else:
                            st.error("🚨 Error: Selected Value Exceeds")  # ✅ Error message shown when API fails

                    except Exception as e:
                        st.error(f"⚠️ Error jumping to time: {e}")  # ✅ Exception handling
                else:
                    st.error("🚨 Selected row does not have a valid 'time' value!")  # ✅ Ensuring valid time
            else:
                st.error("🚨 'time' column not found in the selected data!")  # ✅ Column missing
        else:
            st.warning("⚠️ No row selected! Please select a row to proceed.")  # ✅ No selection warning

    # Jump to Time and Trim Video (Now protected after login)
    st.sidebar.header("🎬 Go to Timestamp")
# 🏃‍♂️ Jump to Time Feature
    jump_time = st.sidebar.text_input("Enter Jump Time (HH:MM:SS AM/PM)")
    if st.sidebar.button("Jump to Time"):
        if "uploaded_video_path" in st.session_state and "initial_time" in st.session_state:
            data = {
                "initial_time": st.session_state["initial_time"],
                "jump_time": jump_time
            }
            response = requests.post(f"{FASTAPI_URL}/jump_to_time/", data=data)

            if response.status_code == 200:
                jump_seconds = response.json()["jump_seconds"]
                video_placeholder.video(st.session_state["uploaded_video_path"], start_time=int(jump_seconds))
            else:
                st.sidebar.error(f"🚨 Error: {response.json().get('error', 'Unknown error')}")

    
    st.sidebar.subheader("✂️ Trim Video")
    start_time = st.sidebar.text_input("⏱️ Start Time (HH:MM:SS AM/PM)")
    end_time = st.sidebar.text_input("⏳ End Time (HH:MM:SS AM/PM)")

    if st.sidebar.button("📥Trim Video"):
        if not start_time or not end_time:
            st.sidebar.error("🚨 Please enter both start and end times!")
        elif "uploaded_video_path" not in st.session_state:
            st.sidebar.error("🚨 Please upload a video first!")
        else:
            trim_data = {
                "file_path": st.session_state["uploaded_video_path"],
                "start_time": start_time,
                "end_time": end_time,
                "initial_time_str": st.session_state["initial_time"]
            }
            with st.spinner("⏳ Trimming video... Please wait!"):
                response = requests.post(f"{FASTAPI_URL}/trim_video/", data=trim_data)

            if response.status_code == 200:
                trimmed_video_path = response.json()["trimmed_video_path"]
                st.sidebar.success(f"✅ Video trimmed successfully!\n📁 Saved at: `{trimmed_video_path}`")
            else:
                st.sidebar.error(f"🚨 Error: {response.json().get('error', 'Unknown error')}")

if not st.session_state["authenticated"]:
    login_page()
else:
    video_upload_page()
