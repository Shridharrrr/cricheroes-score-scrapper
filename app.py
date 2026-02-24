import sys
import asyncio

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import streamlit as st
import json
import os
from playwright.sync_api import sync_playwright
from curl_cffi import requests
from bs4 import BeautifulSoup

@st.cache_resource
def install_playwright():
    os.system("playwright install chromium")
    os.system("playwright install-deps chromium")

install_playwright()

def get_match_data(url):
    # Use a session to persist cookies and headers across requests (handles redirects and nested Cloudflare challenges better)
    session = requests.Session(impersonate="chrome120")
    
    # 1. Fetch the URL using curl_cffi to bypass Cloudflare
    response = session.get(url, timeout=30)
    if response.status_code != 200:
        raise Exception(f"Failed to load URL. Status code: {response.status_code}. Possible Cloudflare block.")
    
    soup = BeautifulSoup(response.text, 'html.parser')
    page_title = soup.title.string if soup.title else ""
    
    if "Just a moment" in page_title or "Cloudflare" in page_title or "Attention Required" in page_title:
        raise Exception(f"Blocked by anti-bot protection. Page Title: '{page_title}'")

    # 2. Figure out the Scorecard URL safely
    real_url = response.url
    if real_url.endswith("/scorecard"):
        pass
    else:
        og_url_tag = soup.find("meta", property="og:url")
        if og_url_tag and og_url_tag.get("content"):
            og_url = og_url_tag["content"]
            if not og_url.startswith("http"):
                og_url = "https://" + og_url
            real_url = og_url + "/scorecard" if not og_url.endswith("/scorecard") else og_url
        else:
            real_url = real_url.rstrip("/") + "/scorecard"

    # 3. Navigate to the actual scorecard page if needed
    if response.url != real_url and not response.url.endswith("/scorecard"):
        response = session.get(real_url, timeout=30)
        if response.status_code != 200:
             raise Exception(f"Failed to load scorecard URL. Status: {response.status_code}")
        soup = BeautifulSoup(response.text, 'html.parser')

    # 4. Extract the __NEXT_DATA__ JSON script
    next_data_tag = soup.find("script", id="__NEXT_DATA__")
    if not next_data_tag:
        raise Exception("Failed to fetch scorecard JSON. The page loaded, but the __NEXT_DATA__ block is missing.")
    
    json_text = next_data_tag.string

    # 5. Parse the extracted JSON
    data = json.loads(json_text)
    page_props = data.get("props", {}).get("pageProps", {})

    scorecard = page_props.get("scorecard", [])
    summary_data = page_props.get("summaryData", {}).get("data", {})

    meta_info = {
        "result": summary_data.get("match_summary", {}).get("summary", "N/A"),
        "man_of_the_match": summary_data.get("player_of_the_match", {}).get("player_name", "N/A"),
        "match_overs": summary_data.get("overs", "N/A"),
        "tournament_name": summary_data.get("tournament_name", "N/A"),
    }

    return {"scorecard": scorecard, "meta": meta_info}


def generate_pdf_bytes(data_packet):
    match_data = data_packet.get("scorecard", [])
    meta_info = data_packet.get("meta", {})

    team1 = match_data[0].get("teamName", "Team A") if len(match_data) > 0 else "Team A"
    team2 = match_data[1].get("teamName", "Team B") if len(match_data) > 1 else "Team B"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{
                font-family: Arial, sans-serif;
                padding: 30px;
            }}
            h1 {{
                text-align: center;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-bottom: 20px;
            }}
            th, td {{
                border: 1px solid black;
                padding: 6px;
                text-align: center;
            }}
            .section-title {{
                background: black;
                color: white;
                padding: 6px;
                font-weight: bold;
            }}
        </style>
    </head>
    <body>

    <h1>Match Scorecard</h1>
    <h2 style="text-align:center;">{meta_info.get("tournament_name")}</h2>
    <h3 style="text-align:center;">{team1} VS {team2}</h3>
    <p><b>Result:</b> {meta_info.get("result")}</p>
    <p><b>Man of the Match:</b> {meta_info.get("man_of_the_match")}</p>
    """

    for inning in match_data:
        team_name = inning.get("teamName", "Unknown")
        score = inning.get("inning", {}).get("summary", {}).get("score", "0/0")

        html_content += f"""
        <div class="section-title">{team_name} - {score}</div>
        <table>
        <tr>
            <th>Batsman</th>
            <th>Runs</th>
            <th>Balls</th>
            <th>4s</th>
            <th>6s</th>
        </tr>
        """

        for b in inning.get("batting", [])[:5]:
            html_content += f"""
            <tr>
                <td>{b.get("name","")}</td>
                <td>{b.get("runs","")}</td>
                <td>{b.get("balls","")}</td>
                <td>{b.get("4s","")}</td>
                <td>{b.get("6s","")}</td>
            </tr>
            """

        html_content += "</table>"

    html_content += "</body></html>"

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--single-process",
                "--disable-gpu"
            ],
        )

        page = browser.new_page()
        page.set_content(html_content, wait_until="networkidle")

        pdf_bytes = page.pdf(
            format="A4",
            print_background=True
        )

        browser.close()
        
    return pdf_bytes

def main():
    st.set_page_config(page_title="Scorecard to PDF", page_icon="🏏")
    
    st.title("🏏 Cricket Scorecard Generator")
    st.write("Enter a match URL below to scrape the scorecard and download it as a PDF.")

    url = st.text_input("Match URL:", placeholder="https://www.example.com/cricket/match-url...")

    if st.button("Generate Scorecard PDF"):
        if not url:
            st.warning("Please enter a valid match URL first.")
            return

        with st.spinner("Scraping match data..."):
            try:
                data_packet = get_match_data(url)
            except Exception as e:
                st.error(f"Error fetching data: {e}")
                return

        with st.spinner("Generating PDF using Playwright..."):
            try:
                pdf_bytes = generate_pdf_bytes(data_packet)
            except Exception as e:
                st.error(f"Error generating PDF: {e}")
                return

        st.success("✓ Scorecard generated successfully!")
        st.download_button(
            label="⬇️ Download PDF",
            data=pdf_bytes,
            file_name="scorecard.pdf",
            mime="application/pdf"
        )

if __name__ == "__main__":
    main()