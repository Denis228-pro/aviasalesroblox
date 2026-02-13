import firebase_admin
from firebase_admin import credentials, firestore
import os
import json


def initialize_firebase():
    """Инициализация Firebase из строки JSON"""
    firebase_config = os.environ.get("FIREBASE_CONFIG")

    if not firebase_config:
        raise ValueError("❌ FIREBASE_CONFIG не найден в секретах Replit!")

    try:
        # Парсим JSON из строки
        cred_dict = json.loads(firebase_config)

        # Инициализируем Firebase
        cred = credentials.Certificate(cred_dict)
        app = firebase_admin.initialize_app(cred)

        # Получаем Firestore
        db = firestore.client()

        print("✅ Firebase успешно инициализирован!")
        return db

    except json.JSONDecodeError as e:
        raise ValueError(f"❌ Ошибка парсинга JSON: {e}")
    except Exception as e:
        raise ValueError(f"❌ Ошибка инициализации Firebase: {e}")


# Создаем глобальный объект базы данных
db = initialize_firebase()
