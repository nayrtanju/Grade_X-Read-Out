Bosch Grade-X Session Analyzer

Kurulum

python -m venv .venv

Windows:

.venv\Scripts\activate
pip install -r requirements.txt
streamlit run streamlit_app.py

macOS/Linux:

source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app.py

Tarayıcıda açılan arayüzden bir veya birden fazla .session dosyası yükleyin. Uygulama ECU özetini gösterir ve iki sayfalı Excel raporu indirmenizi sağlar.

Streamlit Community Cloud

Dosyaları bir GitHub reposuna koyun:

streamlit_app.py

requirements.txt

Ardından Streamlit Community Cloud üzerinde repo ve streamlit_app.py dosyasını seçerek deploy edin.
