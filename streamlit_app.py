import streamlit as st
import yt_dlp
import os

def download_video(url, output_path="downloads"):
    try:
        os.makedirs(output_path, exist_ok=True)

        ydl_opts = {
            'outtmpl': os.path.join(output_path, '%(title)s.%(ext)s'),
            'format': 'bv*[vcodec^=avc]+ba[ext=m4a]/b[ext=mp4]/b',
            'merge_output_format': 'mp4',
            'quiet': True,
            'noplaylist': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Unknown Title')
            filename = os.path.join(output_path, f"{title}.mp4")
            return title, filename
    except Exception as e:
        return None, str(e)

def main():
    st.set_page_config(page_title="YouTube Video Downloader", page_icon="🎬")
    st.title("🎬 YouTube Video Downloader")

    youtube_url = st.text_input("Enter YouTube Video URL:")

    if st.button("Download Video"):
        if youtube_url:
            with st.spinner('Downloading...'):
                title, result = download_video(youtube_url)
                if title:
                    st.success(f"✅ Downloaded: {title}")
                    st.video(result)
                    st.info(f"Saved to 'downloads' folder.")
                else:
                    st.error(f"❌ Error: {result}")
        else:
            st.warning("⚠️ Please enter a valid YouTube URL.")

if __name__ == "__main__":
    main()
