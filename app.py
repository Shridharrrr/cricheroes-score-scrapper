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
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu"
            ]
        )
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        )
        
        # 1. Fetch the INITIAL URL and let Playwright handle any Javascript/Meta redirects natively
        response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
        if response and response.status >= 400 and response.status != 403:
             raise Exception(f"Failed to load URL '{url}'. Status: {response.status}.")
        
        # Wait explicitly until the URL changes away from the shortlink domain.
        # This completely eliminates timing issues with Streamlit servers executing the JS redirect slowly.
        if "chshare.link" in url:
            try:
                page.wait_for_url(lambda u: "chshare.link" not in u, timeout=15000)
            except Exception as e:
                print(f"Warning: URL did not change from shortlink after 15s. Current URL: {page.url}")
        
        # 2. Construct the final scorecard URL if the redirect went to the summary page.
        # We strip query parameters to avoid 404s/403s on the scorecard endpoint.
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(page.url)
        path = parsed.path
        
        if not path.endswith('/scorecard'):
            if path.endswith('/summary'):
                path = path[:-8] # remove '/summary'
            elif path.endswith('/summary/'):
                path = path[:-9]
                
            path = path.rstrip('/') + '/scorecard'
            final_url = urlunparse((parsed.scheme, parsed.netloc, path, '', '', ''))
            
            # Navigate to the actual scorecard page
            response2 = page.goto(final_url, wait_until="domcontentloaded", timeout=60000)
            if response2 and response2.status >= 400 and response2.status != 403:
                 raise Exception(f"Failed to load FINAL URL '{final_url}'. Status: {response2.status}.")
        
        # 3. Wait explicitly for the NextJS data to be injected into the DOM.
        # This automatically waits through Cloudflare "Just a moment" screens
        page.wait_for_selector('script#__NEXT_DATA__', state='attached', timeout=45000)
        
        # 4. Now it is safe to extract the HTML content
        soup = BeautifulSoup(page.content(), 'html.parser')

        # 4. Extract the __NEXT_DATA__ JSON script
        next_data_tag = soup.find("script", id="__NEXT_DATA__")
        browser.close()

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