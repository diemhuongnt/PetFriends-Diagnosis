import os
import urllib
import cv2
import pyodbc
from fastapi import FastAPI, UploadFile, File, Depends
from sqlalchemy import create_engine, Column, Integer, String, Float, TIMESTAMP, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from ultralytics import YOLO
import numpy as np
from sqlalchemy.sql import text

# Khởi tạo FastAPI
app = FastAPI()

# Cấu hình kết nối SQL Server
username = "petfriends"
password = "Admin@123"
server = "160.250.133.192"
database = "petfriends"

# Mã hóa password để xử lý ký tự đặc biệt
password_encoded = urllib.parse.quote_plus(password)

# Cấu hình kết nối với SQLAlchemy
DATABASE_URL = f"mssql+pyodbc://{username}:{password_encoded}@{server}/{database}?driver=ODBC+Driver+17+for+SQL+Server"
engine = create_engine(DATABASE_URL, echo=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Định nghĩa thư mục lưu ảnh chẩn đoán
IMAGE_SAVE_PATH = "./diagnosed_images"
os.makedirs(IMAGE_SAVE_PATH, exist_ok=True)

# Dependency lấy session DB
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Load mô hình YOLO
model = YOLO('best.pt')

# Route kiểm tra API
@app.get("/")
def read_root():
    return {"message": "Welcome to YOLOv11 API. Go to /docs to test the API."}

@app.get("/check-db")
def check_database_connection(db: Session = Depends(get_db)):
    try:
        # Sử dụng text() để tránh lỗi
        sql = text("SELECT 1")
        db.execute(sql)
        return {"message": "Connected to SQL Server successfully!"}
    except Exception as e:
        return {"error": f"Database connection failed: {str(e)}"}

# API chẩn đoán bệnh qua hình ảnh
@app.post("/api/diagnose/predict")
async def predict(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    # Đọc dữ liệu ảnh
    contents = await file.read()
    np_arr = np.frombuffer(contents, np.uint8)
    image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

    # Lưu ảnh vào thư mục diagnosed_images
    file_path = os.path.join(IMAGE_SAVE_PATH, file.filename)
    with open(file_path, "wb") as f:
        f.write(contents)

    # Thực hiện dự đoán
    results = model(image)
    predictions = {}

    for result in results:
        boxes = result.boxes
        for box in boxes:
            label = model.names[int(box.cls)]
            confidence = float(box.conf[0])

            # Loại bỏ phần sau dấu '-' và chuyển thành chữ thường
            clean_label = label.split('-')[0].strip().lower()

            # Truy vấn thông tin bệnh từ database
            sql = text("""
            SELECT description, symptoms, firstAid FROM Diagnoses
            WHERE LOWER(label) = :label
            """)

            result = db.execute(sql, {"label": clean_label}).fetchone()
            if result:
                description, symptoms, firstAid = result
            else:
                description, symptoms, firstAid = "No data", "No data", "No data"

            # Nếu nhãn đã tồn tại trong danh sách, chỉ lấy giá trị confidence lớn nhất
            if clean_label in predictions:
                predictions[clean_label]["confidence"] = max(predictions[clean_label]["confidence"], round(confidence * 100, 2))
            else:
                predictions[clean_label] = {
                    "label": clean_label,
                    "confidence": round(confidence * 100, 2),
                    "description": description,
                    "symptoms": symptoms,
                    "firstAid": firstAid
                }

    # Nếu tất cả nhãn đều giống nhau, chỉ lấy nhãn có confidence cao nhất
    if len(predictions) == 1:
        final_prediction = max(predictions.values(), key=lambda x: x["confidence"])
        return {"predictions": [final_prediction]}
    else:
        return {"predictions": list(predictions.values())}