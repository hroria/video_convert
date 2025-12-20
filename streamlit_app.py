import streamlit as st
import yt_dlp
import os
import re


def _sanitize_filename(name: str) -> str:
    """Remove characters that are invalid in file names."""
    return re.sub(r'[\\/:*?"<>|]', '_', name)

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
            filename = ydl.prepare_filename(info)
            if not filename.endswith(".mp4"):
                filename = os.path.splitext(filename)[0] + ".mp4"

            safe_path = os.path.join(
                os.path.dirname(filename),
                _sanitize_filename(os.path.basename(filename))
            )
            if safe_path != filename and os.path.exists(filename):
                os.rename(filename, safe_path)
            return info.get('title', 'Unknown Title'), safe_path
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
                if title and os.path.exists(result):
                    with open(result, "rb") as f:
                        video_bytes = f.read()
                        st.success(f"✅ Downloaded: {title}")
                        st.download_button(
                            label="📥 Click to Download MP4",
                            data=video_bytes,
                            file_name=os.path.basename(result),
                            mime="video/mp4"
                        )
                else:
                    st.error(f"❌ Error: {result}")
        else:
            st.warning("⚠️ Please enter a valid YouTube URL.")

if __name__ == "__main__":
    main()
