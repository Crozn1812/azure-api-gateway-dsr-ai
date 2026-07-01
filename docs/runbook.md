## 3. Chạy local

### 3.1. Kích hoạt virtual environment

CMD:

.venv\Scripts\activate.bat
### 3.2. Cài dependencies
pip install -r requirements.txt
### 3.3. Chạy server
uvicorn src.main:app --reload

Kết quả mong đợi:

Uvicorn running on http://127.0.0.1:8000
Application startup complete.